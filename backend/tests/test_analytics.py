"""Analytics are computed from stored documents only, per currency, per workspace."""

import uuid
from datetime import date
from decimal import Decimal as D

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, DocumentType


def add(db: Session, **fields) -> None:
    defaults = dict(
        original_filename="x.pdf",
        storage_key=f"originals/{uuid.uuid4()}.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="0" * 64,
        status=DocumentStatus.COMPLETED,
        document_type=DocumentType.INVOICE,
    )
    db.add(Document(**(defaults | fields)))
    db.commit()


def test_empty_workspace(client: TestClient) -> None:
    overview = client.get("/api/analytics/overview").json()
    assert overview["total_documents"] == 0 and overview["spend"] == []
    assert client.get("/api/analytics/spending").json() == {
        "months": [],
        "processed_without_date": 0,
        "outside_window": 0,
    }
    assert client.get("/api/analytics/vendors").json() == {"vendors": []}
    quality = client.get("/api/analytics/quality").json()
    assert quality["processed"] == 0 and quality["latency_ms_median"] is None
    assert quality["review_reasons"] == [] and quality["documents_corrected"] == 0


def test_overview_counts_and_per_currency_spend(client: TestClient, db_session: Session) -> None:
    add(db_session, vendor_name="Acme", total=D("100.00"), currency="USD", invoice_date=date(2025, 3, 1),
        tax=D("8.00"), discount=D("2.00"))  # fmt: skip
    add(db_session, vendor_name="Acme", total=D("50.00"), currency="USD", invoice_date=date(2025, 3, 20),
        status=DocumentStatus.NEEDS_REVIEW, tax=D("4.00"))  # fmt: skip
    add(db_session, vendor_name="Brücke", total=D("80.00"), currency="EUR", invoice_date=date(2025, 4, 2),
        document_type=DocumentType.RECEIPT)  # fmt: skip
    add(db_session, vendor_name="NoCurrency", total=D("10.00"), currency=None, invoice_date=None)
    add(db_session, total=None, status=DocumentStatus.COMPLETED)  # processed, no total found
    add(db_session, status=DocumentStatus.OCR, document_type=None)  # in progress: no money figures
    add(db_session, status=DocumentStatus.FAILED, document_type=None)

    overview = client.get("/api/analytics/overview").json()

    assert (
        overview["total_documents"],
        overview["processed"],
        overview["in_progress"],
        overview["failed"],
    ) == (7, 5, 1, 1)
    assert overview["needs_review"] == 1
    assert overview["type_counts"] == {"INVOICE": 4, "RECEIPT": 1, "UNKNOWN": 0}
    zero = {"tax_total": 0.0, "discount_total": 0.0}
    assert overview["spend"] == [
        {"currency": "USD", "total": 150.0, "document_count": 2, "average": 75.0, "tax_total": 12.0,
         "discount_total": 2.0},
        {"currency": None, "total": 10.0, "document_count": 1, "average": 10.0, **zero},
        {"currency": "EUR", "total": 80.0, "document_count": 1, "average": 80.0, **zero},
    ]  # fmt: skip
    assert overview["processed_without_total"] == 1 and overview["spend_includes_needs_review"] == 1


def test_monthly_spending_and_vendors(client: TestClient, db_session: Session) -> None:
    add(db_session, vendor_name="Acme", total=D("100.00"), currency="USD", invoice_date=date(2025, 3, 1))
    add(db_session, vendor_name="Acme", total=D("50.00"), currency="USD", invoice_date=date(2025, 3, 20))
    add(db_session, vendor_name="Birch", total=D("30.00"), currency="USD", invoice_date=date(2025, 4, 2))
    add(db_session, vendor_name="Birch", total=D("5.00"), currency="USD", invoice_date=None)

    spending = client.get("/api/analytics/spending").json()
    assert spending == {
        "months": [
            {"month": "2025-03", "currency": "USD", "total": 150.0, "document_count": 2},
            {"month": "2025-04", "currency": "USD", "total": 30.0, "document_count": 1},
        ],
        "processed_without_date": 1,
        "outside_window": 0,
    }
    vendors = client.get("/api/analytics/vendors").json()["vendors"]
    assert [(v["vendor"], v["total"], v["document_count"]) for v in vendors] == [
        ("Acme", 150.0, 2),
        ("Birch", 35.0, 2),
    ]


def test_status_counts_only_include_present_statuses(client: TestClient, db_session: Session) -> None:
    # Regression: reading counts from a defaultdict inserted every status with 0.
    add(db_session, total=D("1.00"), currency="USD")
    assert client.get("/api/analytics/overview").json()["status_counts"] == {"COMPLETED": 1}


def test_vendor_names_group_case_and_space_insensitively(client: TestClient, db_session: Session) -> None:
    add(db_session, vendor_name="Acme Ltd", total=D("10.00"), currency="USD")
    add(db_session, vendor_name="ACME LTD ", total=D("5.00"), currency="USD")
    vendors = client.get("/api/analytics/vendors").json()["vendors"]
    assert [(v["total"], v["document_count"]) for v in vendors] == [(15.0, 2)]


def test_monthly_chart_window_is_bounded(client: TestClient, db_session: Session) -> None:
    add(db_session, total=D("1.00"), currency="USD", invoice_date=date(2025, 6, 1))
    add(db_session, total=D("2.00"), currency="USD", invoice_date=date(2023, 6, 1))  # 24 months earlier
    add(db_session, total=D("4.00"), currency="USD", invoice_date=date(2023, 7, 1))  # first month in window
    spending = client.get("/api/analytics/spending").json()
    assert [m["month"] for m in spending["months"]] == ["2023-07", "2025-06"]
    assert spending["outside_window"] == 1


def test_quality_from_real_records(client: TestClient) -> None:
    from tests import invoice_texts as T
    from tests.samples import make_text_pdf

    def upload(text: str) -> str:
        files = {"file": ("x.pdf", make_text_pdf(text), "application/pdf")}
        return client.post("/api/documents/upload", files=files).json()["id"]

    upload(T.STANDARD_INVOICE)
    mismatch = upload(T.TOTALS_MISMATCH)
    upload(T.MISSING_NUMBER_AND_TAX)
    client.patch(f"/api/documents/{mismatch}/extraction", json={"fields": {"total": "2195.00"}})

    quality = client.get("/api/analytics/quality").json()
    assert quality["processed"] == 3 and quality["latency_jobs"] == 3
    assert 0 < quality["latency_ms_median"] <= quality["latency_ms_p95"]
    assert {"key": "missing_required_field", "count": 1} in quality["review_reasons"]
    completeness = {c["field"]: (c["found"], c["processed"]) for c in quality["completeness"]}
    assert completeness["invoice_number"] == (2, 3) and completeness["total"] == (3, 3)
    assert quality["corrected_fields"] == [{"key": "total", "count": 1}]
    assert quality["documents_corrected"] == 1


def test_quality_is_private_to_the_workspace(client: TestClient, db_session: Session) -> None:
    add(db_session, total=D("1.00"), currency="USD")
    other = client.get("/api/analytics/quality", headers={"X-Workspace-Token": "d" * 40}).json()
    assert other["processed"] == 0
