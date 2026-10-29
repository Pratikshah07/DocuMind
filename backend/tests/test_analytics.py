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
    assert client.get("/api/analytics/spending").json() == {"months": [], "processed_without_date": 0}
    assert client.get("/api/analytics/vendors").json() == {"vendors": []}


def test_overview_counts_and_per_currency_spend(client: TestClient, db_session: Session) -> None:
    add(db_session, vendor_name="Acme", total=D("100.00"), currency="USD", invoice_date=date(2025, 3, 1))
    add(db_session, vendor_name="Acme", total=D("50.00"), currency="USD", invoice_date=date(2025, 3, 20),
        status=DocumentStatus.NEEDS_REVIEW)  # fmt: skip
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
    assert overview["spend"] == [
        {"currency": "USD", "total": 150.0, "document_count": 2, "average": 75.0},
        {"currency": None, "total": 10.0, "document_count": 1, "average": 10.0},
        {"currency": "EUR", "total": 80.0, "document_count": 1, "average": 80.0},
    ]
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
