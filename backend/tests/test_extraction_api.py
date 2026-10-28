"""GET/PATCH /documents/{id}/extraction."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus
from tests import invoice_texts as T
from tests.samples import make_text_pdf


def upload_text(client: TestClient, *pages: str) -> str:
    response = client.post(
        "/api/documents/upload", files={"file": ("invoice.pdf", make_text_pdf(*pages), "application/pdf")}
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def by_name(body: dict) -> dict[str, dict]:
    return {f["name"]: f for f in body["fields"]}


def test_get_extraction_of_complete_invoice(client: TestClient) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)

    response = client.get(f"/api/documents/{document_id}/extraction")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED" and body["needs_review"] is False
    assert body["document_type"] == "INVOICE" and 0.8 < body["document_type_confidence"] <= 1
    fields = by_name(body)
    assert [f["name"] for f in body["fields"]][:4] == [
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "due_date",
    ]
    assert fields["total"] == {
        "name": "total",
        "status": "ok",
        "value": "4,820.00",
        "normalized_value": 4820.0,
        "confidence": 0.95,
        "effective_confidence": 0.95,
        "confidence_level": "high",
        "method": "regex",
        "page_number": 1,
        "required": True,
        "is_user_edited": False,
    }
    assert fields["invoice_date"]["normalized_value"] == "2025-03-18"
    assert (
        fields["shipping_address"]["status"] == "missing" and fields["shipping_address"]["required"] is False
    )
    assert fields["vendor_name"]["confidence_level"] == "medium"  # layout heuristic, not a labelled value
    assert [i["description"] for i in body["line_items"]] == [
        "Brand identity refinement",
        "Web design consultation",
    ]
    assert body["line_items"][1]["unit_price"] == 212.5
    assert body["warnings"] == []


def test_problem_document_explains_itself(client: TestClient) -> None:
    document_id = upload_text(client, T.TOTALS_MISMATCH)

    body = client.get(f"/api/documents/{document_id}/extraction").json()

    assert body["status"] == "NEEDS_REVIEW" and body["needs_review"] is True
    [warning] = body["warnings"]
    assert warning["code"] == "totals_mismatch" and warning["field"] == "total"
    fields = by_name(body)
    assert fields["total"]["status"] == "uncertain"
    assert fields["total"]["effective_confidence"] < fields["total"]["confidence"]
    # The detail endpoint carries the same stored rows.
    detail = client.get(f"/api/documents/{document_id}").json()
    assert detail["status"] == "NEEDS_REVIEW" and detail["warnings"][0]["code"] == "totals_mismatch"


def test_extraction_not_ready_and_not_found(client: TestClient, db_session: Session) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)
    document = db_session.get(Document, uuid.UUID(document_id))
    document.status = DocumentStatus.OCR  # e.g. still processing
    db_session.commit()

    response = client.get(f"/api/documents/{document_id}/extraction")
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "extraction_not_ready",
        "message": "Extraction results are not available for this document yet.",
        "details": {"status": "OCR"},
    }
    assert client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {}}).status_code == 409
    assert client.get(f"/api/documents/{uuid.uuid4()}/extraction").status_code == 404


def test_patch_fixes_a_missing_field_and_revalidates(client: TestClient) -> None:
    document_id = upload_text(client, T.MISSING_NUMBER_AND_TAX)
    before = client.get(f"/api/documents/{document_id}/extraction").json()
    assert before["status"] == "NEEDS_REVIEW"
    assert [w["code"] for w in before["warnings"]] == ["missing_required_field"]

    response = client.patch(
        f"/api/documents/{document_id}/extraction", json={"fields": {"invoice_number": "AO-4471"}}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED" and body["warnings"] == []
    field = by_name(body)["invoice_number"]
    assert field == {
        **field,
        "value": "AO-4471",
        "status": "ok",
        "method": "user",
        "confidence": 1.0,
        "is_user_edited": True,
        "page_number": None,
    }
    assert client.get(f"/api/documents/{document_id}").json()["invoice_number"] == "AO-4471"


def test_patch_resolves_totals_mismatch(client: TestClient) -> None:
    document_id = upload_text(client, T.TOTALS_MISMATCH)

    body = client.patch(
        f"/api/documents/{document_id}/extraction", json={"fields": {"total": "2195.00"}}
    ).json()

    assert body["status"] == "COMPLETED" and body["warnings"] == []
    assert by_name(body)["total"]["normalized_value"] == 2195.0


def test_patch_keeps_unrelated_extraction_warnings(client: TestClient) -> None:
    document_id = upload_text(client, T.AMBIGUOUS_DATE)

    still = client.patch(
        f"/api/documents/{document_id}/extraction", json={"fields": {"vendor_name": "P&P"}}
    ).json()
    assert [w["code"] for w in still["warnings"]] == ["ambiguous_date"]  # date not touched → still ambiguous

    fixed = client.patch(
        f"/api/documents/{document_id}/extraction", json={"fields": {"invoice_date": "2025-03-04"}}
    ).json()
    assert fixed["warnings"] == [] and fixed["status"] == "COMPLETED"
    assert by_name(fixed)["vendor_name"]["is_user_edited"] is True  # earlier edit preserved


def test_patch_rejects_invalid_values_atomically(client: TestClient) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)
    before = client.get(f"/api/documents/{document_id}/extraction").json()

    response = client.patch(
        f"/api/documents/{document_id}/extraction",
        json={
            "fields": {
                "invoice_number": "NEW-1",
                "invoice_date": "31/02/2025",
                "total": "abc",
                "currency": "dollars",
                "due_date": "03/04/2025",
            }
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert {d["field"] for d in error["details"]} == {"invoice_date", "total", "currency", "due_date"}
    assert client.get(f"/api/documents/{document_id}/extraction").json() == before  # nothing applied


def test_patch_rejects_unknown_fields(client: TestClient) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)
    response = client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {"iban": "X"}})
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_failed"


def test_patch_clearing_a_required_field_sends_to_review(client: TestClient) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)

    body = client.patch(
        f"/api/documents/{document_id}/extraction", json={"fields": {"invoice_number": None}}
    ).json()

    assert body["status"] == "NEEDS_REVIEW"
    field = by_name(body)["invoice_number"]
    assert field["status"] == "missing" and field["is_user_edited"] is True
    assert client.get(f"/api/documents/{document_id}").json()["invoice_number"] is None


def test_patch_line_items_and_document_type(client: TestClient) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)

    body = client.patch(
        f"/api/documents/{document_id}/extraction",
        json={
            "document_type": "RECEIPT",
            "line_items": [{"description": "Design work", "quantity": 1, "unit_price": 4000, "total": 4000}],
        },
    ).json()

    assert body["document_type"] == "RECEIPT" and body["document_type_user_edited"] is True
    assert [i["description"] for i in body["line_items"]] == ["Design work"]
    assert by_name(body)["invoice_number"]["required"] is False  # receipt rules now apply
    assert [w["code"] for w in body["warnings"]] == ["line_items_mismatch"]  # 4000 ≠ subtotal 4500
    assert body["status"] == "NEEDS_REVIEW"


def test_patch_is_idempotent(client: TestClient) -> None:
    document_id = upload_text(client, T.TOTALS_MISMATCH)
    payload = {"fields": {"total": "2195.00", "currency": "usd"}}

    first = client.patch(f"/api/documents/{document_id}/extraction", json=payload).json()
    second = client.patch(f"/api/documents/{document_id}/extraction", json=payload).json()

    assert first == second
    assert by_name(second)["currency"]["value"] == "USD"
    assert len(second["fields"]) == 12 and len(second["line_items"]) == 2


def test_reprocessing_replaces_user_edits(client: TestClient) -> None:
    document_id = upload_text(client, T.MISSING_NUMBER_AND_TAX)
    client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {"invoice_number": "AO-4471"}})

    assert client.post(f"/api/documents/{document_id}/process").status_code == 202

    body = client.get(f"/api/documents/{document_id}/extraction").json()
    assert by_name(body)["invoice_number"]["status"] == "missing"  # fresh extraction (D35)
    assert body["status"] == "NEEDS_REVIEW"
