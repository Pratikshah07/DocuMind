"""Workspace analytics computed from stored documents (no estimates, no sample data).

Aggregation runs in the database (GROUP BY), always filtered by workspace, so the work
and the data transferred stay proportional to the number of groups, not documents.
Supersedes D45's in-Python aggregation.

Money is only ever summed within one currency. Documents whose currency wasn't found are
grouped under ``currency = None`` and never mixed with others. Only processed documents
(COMPLETED or NEEDS_REVIEW) contribute money figures; the number still awaiting review is
reported so the UI can say so. Values are as extracted (or as corrected by the user):
they are not audited figures.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import median

from sqlalchemy import Integer, and_, case, distinct, extract, func, select
from sqlalchemy.orm import Session

from app.core.workspace import LOCAL_WORKSPACE
from app.models import (
    Document,
    DocumentStatus,
    DocumentType,
    ExtractedField,
    ExtractionEdit,
    JobStatus,
    ProcessingJob,
    ValidationWarning,
    WarningSeverity,
)
from app.services.extraction.types import FIELD_NAMES, REQUIRED_FIELDS

PROCESSED = (DocumentStatus.COMPLETED, DocumentStatus.NEEDS_REVIEW)
IN_PROGRESS = (
    DocumentStatus.UPLOADED,
    DocumentStatus.PROCESSING,
    DocumentStatus.OCR,
    DocumentStatus.EXTRACTING,
    DocumentStatus.VALIDATING,
)
SPENDING_MONTHS = 24  # monthly chart window, counted back from the latest dated document
LATENCY_SAMPLE = 500  # most recent successful jobs used for latency percentiles


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


@dataclass
class CurrencyTotal:
    currency: str | None
    total: Decimal = Decimal("0")
    document_count: int = 0
    tax_total: Decimal = Decimal("0")
    discount_total: Decimal = Decimal("0")

    @property
    def average(self) -> Decimal:
        return (
            (self.total / self.document_count).quantize(Decimal("0.01"))
            if self.document_count
            else Decimal(0)
        )


@dataclass
class Overview:
    total_documents: int
    processed: int
    in_progress: int
    needs_review: int
    failed: int
    status_counts: dict[str, int]
    type_counts: dict[str, int]
    spend: list[CurrencyTotal]
    processed_without_total: int
    spend_includes_needs_review: int


@dataclass
class MonthTotal:
    month: str  # YYYY-MM, from the document's invoice date
    currency: str | None
    total: Decimal
    document_count: int


@dataclass
class VendorTotal:
    vendor: str
    currency: str | None
    total: Decimal
    document_count: int


@dataclass
class Spending:
    months: list[MonthTotal] = field(default_factory=list)
    processed_without_date: int = 0
    outside_window: int = 0  # dated documents older than the chart window


@dataclass
class Count:
    key: str
    count: int


@dataclass
class Completeness:
    field: str
    found: int
    processed: int


@dataclass
class Quality:
    processed: int
    latency_ms_median: int | None
    latency_ms_p95: int | None
    latency_jobs: int
    review_reasons: list[Count]
    completeness: list[Completeness]
    corrected_fields: list[Count]
    documents_corrected: int


class AnalyticsService:
    def __init__(self, db: Session, *, workspace_id: str = LOCAL_WORKSPACE) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def _scoped(self):
        return Document.workspace_id == self.workspace_id

    def _processed(self):
        return and_(self._scoped(), Document.status.in_(PROCESSED))

    def overview(self) -> Overview:
        status_counts = {
            status.value: count
            for status, count in self.db.execute(
                select(Document.status, func.count()).where(self._scoped()).group_by(Document.status)
            )
        }
        type_counts = {t.value: 0 for t in DocumentType}
        for doc_type, count in self.db.execute(
            select(Document.document_type, func.count())
            .where(self._processed())
            .group_by(Document.document_type)
        ):
            type_counts[doc_type.value if doc_type else "UNCLASSIFIED"] = count

        spend = [
            CurrencyTotal(currency, _money(total), count, _money(tax), _money(discount))
            for currency, total, count, tax, discount in self.db.execute(
                select(
                    Document.currency,
                    func.sum(Document.total),
                    func.count(),
                    func.sum(Document.tax),
                    func.sum(Document.discount),
                )
                .where(self._processed(), Document.total.is_not(None))
                .group_by(Document.currency)
            )
        ]
        without_total, unreviewed = self.db.execute(
            select(
                func.coalesce(func.sum(case((Document.total.is_(None), 1), else_=0)), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Document.total.is_not(None),
                                    Document.status == DocumentStatus.NEEDS_REVIEW,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(self._processed())
        ).one()
        return Overview(
            total_documents=sum(status_counts.values()),
            processed=sum(status_counts.get(s.value, 0) for s in PROCESSED),
            in_progress=sum(status_counts.get(s.value, 0) for s in IN_PROGRESS),
            needs_review=status_counts.get(DocumentStatus.NEEDS_REVIEW.value, 0),
            failed=status_counts.get(DocumentStatus.FAILED.value, 0),
            status_counts=status_counts,
            type_counts=type_counts,
            spend=sorted(spend, key=lambda c: (-c.document_count, c.currency or "")),
            processed_without_total=int(without_total),
            spend_includes_needs_review=int(unreviewed),
        )

    def spending(self, months: int = SPENDING_MONTHS) -> Spending:
        result = Spending()
        with_total = and_(self._processed(), Document.total.is_not(None))
        result.processed_without_date = (
            self.db.scalar(select(func.count()).where(with_total, Document.invoice_date.is_(None))) or 0
        )
        latest: date | None = self.db.scalar(select(func.max(Document.invoice_date)).where(with_total))
        if latest is None:
            return result
        start_index = latest.year * 12 + latest.month - 1 - (months - 1)
        start = date(start_index // 12, start_index % 12 + 1, 1)
        result.outside_window = (
            self.db.scalar(select(func.count()).where(with_total, Document.invoice_date < start)) or 0
        )
        year = extract("year", Document.invoice_date).cast(Integer)
        month = extract("month", Document.invoice_date).cast(Integer)
        rows = self.db.execute(
            select(year, month, Document.currency, func.sum(Document.total), func.count())
            .where(with_total, Document.invoice_date >= start)
            .group_by(year, month, Document.currency)
        )
        result.months = sorted(
            (
                MonthTotal(f"{y:04d}-{m:02d}", currency, _money(total), count)
                for y, m, currency, total, count in rows
            ),
            key=lambda m: (m.month, m.currency or ""),
        )
        return result

    def vendors(self, limit: int = 10) -> list[VendorTotal]:
        # Group case- and whitespace-insensitively; show one spelling (the alphabetically first).
        key = func.lower(func.trim(Document.vendor_name))
        total = func.sum(Document.total)
        rows = self.db.execute(
            select(func.min(func.trim(Document.vendor_name)), Document.currency, total, func.count())
            .where(
                self._processed(), Document.total.is_not(None), Document.vendor_name.is_not(None), key != ""
            )
            .group_by(key, Document.currency)
            .order_by(total.desc(), key)
            .limit(limit)
        )
        return [VendorTotal(vendor, currency, _money(t), count) for vendor, currency, t, count in rows]

    def quality(self) -> Quality:
        processed = self.db.scalar(select(func.count()).where(self._processed())) or 0

        durations = list(
            self.db.scalars(
                select(ProcessingJob.duration_ms)
                .join(Document, Document.id == ProcessingJob.document_id)
                .where(
                    self._scoped(),
                    ProcessingJob.status == JobStatus.SUCCEEDED,
                    ProcessingJob.duration_ms.is_not(None),
                )
                .order_by(ProcessingJob.finished_at.desc())
                .limit(LATENCY_SAMPLE)
            )
        )
        ordered = sorted(durations)
        p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))] if ordered else None

        reasons = [
            Count(code, count)
            for code, count in self.db.execute(
                select(ValidationWarning.code, func.count(distinct(ValidationWarning.document_id)))
                .join(Document, Document.id == ValidationWarning.document_id)
                .where(self._processed(), ValidationWarning.severity != WarningSeverity.INFO)
                .group_by(ValidationWarning.code)
                .order_by(func.count(distinct(ValidationWarning.document_id)).desc(), ValidationWarning.code)
                .limit(10)
            )
        ]

        tracked = sorted(
            {name for names in REQUIRED_FIELDS.values() for name in names}, key=FIELD_NAMES.index
        )
        tracked += [
            n for n in ("due_date", "currency", "subtotal", "tax", "payment_method") if n not in tracked
        ]
        found = dict(
            self.db.execute(
                select(ExtractedField.name, func.count())
                .join(Document, Document.id == ExtractedField.document_id)
                .where(self._processed(), ExtractedField.value.is_not(None), ExtractedField.name.in_(tracked))
                .group_by(ExtractedField.name)
            ).all()
        )

        edits = self.db.execute(
            select(ExtractionEdit.field, func.count(distinct(ExtractionEdit.document_id)))
            .join(Document, Document.id == ExtractionEdit.document_id)
            .where(self._scoped(), ExtractionEdit.kind == "edit", ExtractionEdit.field.is_not(None))
            .group_by(ExtractionEdit.field)
            .order_by(func.count(distinct(ExtractionEdit.document_id)).desc(), ExtractionEdit.field)
            .limit(10)
        ).all()
        corrected_docs = (
            self.db.scalar(
                select(func.count(distinct(ExtractionEdit.document_id)))
                .join(Document, Document.id == ExtractionEdit.document_id)
                .where(self._scoped(), ExtractionEdit.kind == "edit")
            )
            or 0
        )
        return Quality(
            processed=processed,
            latency_ms_median=int(median(ordered)) if ordered else None,
            latency_ms_p95=p95,
            latency_jobs=len(ordered),
            review_reasons=reasons,
            completeness=[Completeness(name, found.get(name, 0), processed) for name in tracked],
            corrected_fields=[Count(name, count) for name, count in edits],
            documents_corrected=corrected_docs,
        )
