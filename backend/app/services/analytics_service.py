"""Workspace analytics computed from stored documents (no estimates, no sample data).

Money is only ever summed within one currency. Documents whose currency wasn't
found are grouped under ``currency = None`` and never mixed with others. Only
processed documents (COMPLETED or NEEDS_REVIEW) contribute money figures; the
number still awaiting review is reported so the UI can say so.

Aggregation happens in Python over the workspace's rows: workspaces are capped
(MAX_DOCUMENTS_PER_WORKSPACE), and it keeps the month bucketing portable between
SQLite and PostgreSQL.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.workspace import LOCAL_WORKSPACE
from app.models import Document, DocumentStatus, DocumentType

PROCESSED = (DocumentStatus.COMPLETED, DocumentStatus.NEEDS_REVIEW)
IN_PROGRESS = (
    DocumentStatus.UPLOADED,
    DocumentStatus.PROCESSING,
    DocumentStatus.OCR,
    DocumentStatus.EXTRACTING,
    DocumentStatus.VALIDATING,
)


@dataclass
class CurrencyTotal:
    currency: str | None
    total: Decimal = Decimal("0")
    document_count: int = 0

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


class AnalyticsService:
    def __init__(self, db: Session, *, workspace_id: str = LOCAL_WORKSPACE) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def _documents(self) -> list[Document]:
        return list(self.db.scalars(select(Document).where(Document.workspace_id == self.workspace_id)).all())

    def overview(self) -> Overview:
        docs = self._documents()
        status_counts: dict[str, int] = defaultdict(int)
        type_counts: dict[str, int] = defaultdict(int)
        spend: dict[str | None, CurrencyTotal] = {}
        without_total = unreviewed_in_spend = 0
        for doc in docs:
            status_counts[doc.status.value] += 1
            if doc.status not in PROCESSED:
                continue
            type_counts[doc.document_type.value if doc.document_type else "UNCLASSIFIED"] += 1
            if doc.total is None:
                without_total += 1
                continue
            bucket = spend.setdefault(doc.currency, CurrencyTotal(doc.currency))
            bucket.total += doc.total
            bucket.document_count += 1
            unreviewed_in_spend += doc.status == DocumentStatus.NEEDS_REVIEW
        counts = dict(status_counts)  # plain dict: .get() never inserts zero entries
        return Overview(
            total_documents=len(docs),
            processed=sum(counts.get(s.value, 0) for s in PROCESSED),
            in_progress=sum(counts.get(s.value, 0) for s in IN_PROGRESS),
            needs_review=counts.get(DocumentStatus.NEEDS_REVIEW.value, 0),
            failed=counts.get(DocumentStatus.FAILED.value, 0),
            status_counts=counts,
            type_counts={**{t.value: 0 for t in DocumentType}, **type_counts},
            spend=sorted(spend.values(), key=lambda c: (-c.document_count, c.currency or "")),
            processed_without_total=without_total,
            spend_includes_needs_review=unreviewed_in_spend,
        )

    def spending(self) -> Spending:
        result = Spending()
        buckets: dict[tuple[str, str | None], MonthTotal] = {}
        for doc in self._documents():
            if doc.status not in PROCESSED or doc.total is None:
                continue
            if doc.invoice_date is None:
                result.processed_without_date += 1
                continue
            key = (doc.invoice_date.strftime("%Y-%m"), doc.currency)
            bucket = buckets.setdefault(key, MonthTotal(key[0], doc.currency, Decimal("0"), 0))
            bucket.total += doc.total
            bucket.document_count += 1
        result.months = sorted(buckets.values(), key=lambda m: (m.month, m.currency or ""))
        return result

    def vendors(self, limit: int = 10) -> list[VendorTotal]:
        buckets: dict[tuple[str, str | None], VendorTotal] = {}
        for doc in self._documents():
            if doc.status not in PROCESSED or doc.total is None or not doc.vendor_name:
                continue
            key = (doc.vendor_name.strip(), doc.currency)
            bucket = buckets.setdefault(key, VendorTotal(key[0], doc.currency, Decimal("0"), 0))
            bucket.total += doc.total
            bucket.document_count += 1
        return sorted(buckets.values(), key=lambda v: (-v.total, v.vendor))[:limit]
