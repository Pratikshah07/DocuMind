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
    # Located on the page: the "Total Due  USD 4,820.00" line, right of the label.
    x0, y0, x1, y1 = fields["total"].pop("bbox")
    assert 0 < x0 < x1 < 1 and 0.35 < y0 < y1 < 0.45
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
    assert len(second["fields"]) == 15 and len(second["line_items"]) == 2


def test_reprocessing_keeps_user_corrections(client: TestClient) -> None:
    document_id = upload_text(client, T.MISSING_NUMBER_AND_TAX)
    patched = client.patch(
        f"/api/documents/{document_id}/extraction",
        json={
            "fields": {"invoice_number": "AO-4471", "tax": "0"},
            "document_type": "INVOICE",
            "line_items": [
                {"description": "Consulting", "quantity": "2", "unit_price": "50", "total": "100"}
            ],
        },
    ).json()

    assert client.post(f"/api/documents/{document_id}/process").status_code == 202

    body = client.get(f"/api/documents/{document_id}/extraction").json()
    fields = by_name(body)
    assert fields["invoice_number"]["value"] == "AO-4471" and fields["invoice_number"]["is_user_edited"]
    assert fields["invoice_number"]["method"] == "user"
    assert fields["tax"]["normalized_value"] == 0
    assert body["document_type_user_edited"] is True
    assert body["line_items_user_edited"] is True
    assert [i["description"] for i in body["line_items"]] == ["Consulting"]
    # Validation ran again over the corrected values: same result as right after the PATCH.
    assert body["status"] == patched["status"]
    assert {w["code"] for w in body["warnings"]} == {w["code"] for w in patched["warnings"]}


def test_reprocessing_can_discard_corrections(client: TestClient) -> None:
    document_id = upload_text(client, T.MISSING_NUMBER_AND_TAX)
    client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {"invoice_number": "AO-4471"}})

    response = client.post(f"/api/documents/{document_id}/process", params={"discard_corrections": "true"})
    assert response.status_code == 202

    body = client.get(f"/api/documents/{document_id}/extraction").json()
    assert by_name(body)["invoice_number"]["status"] == "missing"  # as extracted from the file
    assert body["line_items_user_edited"] is False
    assert body["status"] == "NEEDS_REVIEW"
    # The discarded correction is still in the history, followed by the reset.
    edits = client.get(f"/api/documents/{document_id}/edits").json()["edits"]
    assert [(e["kind"], e["field"], e["old_value"], e["new_value"]) for e in edits] == [
        ("edit", "invoice_number", None, "AO-4471"),
        ("reset", None, None, None),
    ]
    # A later reprocess does not bring the discarded correction back.
    client.post(f"/api/documents/{document_id}/process")
    body = client.get(f"/api/documents/{document_id}/extraction").json()
    assert by_name(body)["invoice_number"]["status"] == "missing"


def test_corrections_survive_a_failed_reprocess(
    client: TestClient, db_session: Session, fake_ocr, storage
) -> None:
    document_id = upload_text(client, T.MISSING_NUMBER_AND_TAX)
    client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {"invoice_number": "AO-4471"}})
    original = db_session.get(Document, uuid.UUID(document_id)).storage_key
    content = storage.open(original).read()

    storage.delete(original)  # the next run fails: file_missing
    client.post(f"/api/documents/{document_id}/process")
    assert client.get(f"/api/documents/{document_id}/status").json()["status"] == "FAILED"

    from io import BytesIO

    storage.save(original, BytesIO(content))  # file back: the retry succeeds and re-applies the edit
    client.post(f"/api/documents/{document_id}/process")
    body = client.get(f"/api/documents/{document_id}/extraction").json()
    assert by_name(body)["invoice_number"]["value"] == "AO-4471"


def test_edit_history_records_old_and_new_values(client: TestClient) -> None:
    document_id = upload_text(client, T.STANDARD_INVOICE)
    client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {"total": "4800.00"}})
    client.patch(
        f"/api/documents/{document_id}/extraction", json={"fields": {"total": "4,820.00", "due_date": ""}}
    )
    # Re-submitting the same value is a confirmation and is recorded too.
    client.patch(f"/api/documents/{document_id}/extraction", json={"fields": {"total": "4,820.00"}})

    edits = client.get(f"/api/documents/{document_id}/edits").json()["edits"]
    assert [(e["field"], e["old_value"], e["new_value"]) for e in edits] == [
        ("total", "4,820.00", "4800.00"),
        ("total", "4800.00", "4,820.00"),
        ("due_date", "17/04/2025", None),  # old value exactly as printed
        ("total", "4,820.00", "4,820.00"),
    ]


def test_edit_history_is_private_to_the_workspace(client: TestClient) -> None:
    headers = {"X-Workspace-Token": "a" * 40}
    response = client.post(
        "/api/documents/upload",
        files={"file": ("x.pdf", make_text_pdf(T.STANDARD_INVOICE), "application/pdf")},
        headers=headers,
    )
    document_id = response.json()["id"]
    assert client.get(f"/api/documents/{document_id}/edits").status_code == 404  # other workspace
    assert client.get(f"/api/documents/{document_id}/edits", headers=headers).status_code == 200


def test_warnings_carry_page_and_suggested_action(client: TestClient) -> None:
    document_id = upload_text(client, T.TOTALS_MISMATCH)
    warnings = client.get(f"/api/documents/{document_id}/extraction").json()["warnings"]
    mismatch = next(w for w in warnings if w["code"] == "totals_mismatch")
    assert mismatch["field"] == "total" and mismatch["page_number"] == 1
    assert "Compare subtotal, tax, discount and total" in mismatch["suggested_action"]


def test_same_invoice_twice_is_flagged_on_the_later_copy(client: TestClient) -> None:
    content = make_text_pdf(T.STANDARD_INVOICE)
    first = client.post("/api/documents/upload", files={"file": ("a.pdf", content, "application/pdf")})
    second = client.post(
        "/api/documents/upload",
        files={"file": ("b.pdf", content, "application/pdf")},
        params={"allow_duplicate": "true"},
    )
    body = client.get(f"/api/documents/{second.json()['id']}/extraction").json()
    duplicate = [w for w in body["warnings"] if w["code"] == "duplicate_invoice_number"]
    assert duplicate and "a.pdf" in duplicate[0]["message"] and body["status"] == "NEEDS_REVIEW"
    first_body = client.get(f"/api/documents/{first.json()['id']}/extraction").json()
    assert first_body["status"] == "COMPLETED"  # it was alone when it was processed

    # Correcting the invoice number on the copy clears the warning.
    patched = client.patch(
        f"/api/documents/{second.json()['id']}/extraction", json={"fields": {"invoice_number": "NS-1049"}}
    ).json()
    assert not any(w["code"] == "duplicate_invoice_number" for w in patched["warnings"])


def test_duplicate_invoice_check_stays_inside_the_workspace(client: TestClient) -> None:
    content = make_text_pdf(T.STANDARD_INVOICE)
    client.post("/api/documents/upload", files={"file": ("a.pdf", content, "application/pdf")})
    other = client.post(
        "/api/documents/upload",
        files={"file": ("a.pdf", content, "application/pdf")},
        headers={"X-Workspace-Token": "c" * 40},
    ).json()
    body = client.get(
        f"/api/documents/{other['id']}/extraction", headers={"X-Workspace-Token": "c" * 40}
    ).json()
    assert not any(w["code"] == "duplicate_invoice_number" for w in body["warnings"])
