"""Upload receipts distinguish extraction failures and make response-loss retries safe."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.contract_checker.tests.test_documents import pdf_bytes
from app.api.main import create_app
from app.core.settings import Settings
from app.intake import service as intake
from tests.conftest import EmptyAgent


@pytest.fixture
def client(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(intake, "UPLOADS_DIR", tmp_path / ".uploads")
    with TestClient(create_app(settings)) as client:
        client.app.state.service.agents = [EmptyAgent()]  # type: ignore[attr-defined]
        yield client


def test_receipt_identifies_readable_email_and_retry_does_not_duplicate_it(
    client: TestClient,
) -> None:
    case_id = client.post("/cases", json={"student": {}}).json()["case_id"]
    endpoint = f"/cases/{case_id}/evidence?include_receipt=true"
    form = {"kind": "email", "request_id": str(uuid4()), "student_name": "Sam"}
    files = {"file": ("email.pdf", pdf_bytes("Viewing is confirmed for Tuesday."))}
    first = client.post(endpoint, data=form, files=files)
    assert first.status_code == 200
    saved = first.json()
    assert saved["read_error"] is None
    assert saved["case"]["messages"][0]["text"] == "Viewing is confirmed for Tuesday."
    assert saved["case"]["messages"][0]["evidence_id"] == saved["evidence_id"]
    assert client.portal
    client.portal.call(client.app.state.service.wait_idle)  # type: ignore[attr-defined]
    assert client.post(f"/cases/{case_id}/decide").status_code == 200

    # A lost response must be recoverable even if analysis decided the case before Retry.
    form["student_name"] = "student"  # a reloaded browser need not recover the old profile name
    retried = client.post(endpoint, data=form, files=files)
    assert retried.status_code == 200
    assert retried.json()["evidence_id"] == saved["evidence_id"]
    assert len(retried.json()["case"]["evidence"]) == 1
    assert len(retried.json()["case"]["messages"]) == 1
    form["request_id"] = str(uuid4())
    assert client.post(endpoint, data=form, files=files).status_code == 409


def test_unreadable_receipt_is_saved_and_is_not_a_successful_read(client: TestClient) -> None:
    case_id = client.post("/cases", json={"student": {}}).json()["case_id"]
    endpoint = f"/cases/{case_id}/evidence?include_receipt=true"
    form = {"kind": "email", "request_id": str(uuid4())}
    files = {"file": ("scan.pdf", pdf_bytes(None))}
    response = client.post(endpoint, data=form, files=files)
    assert response.status_code == 200
    body = response.json()
    assert "selectable text" in body["read_error"]
    assert body["case"]["evidence"][0]["extracted_text"] is None
    assert body["case"]["messages"] == []
    assert body["read_error"] == body["case"]["chat"][-1]["text"]
    repeated = client.post(endpoint, data=form, files=files).json()
    assert repeated["read_error"]
    assert len(repeated["case"]["evidence"]) == 1


def test_same_request_id_with_different_bytes_is_not_mistaken_for_saved_evidence(
    client: TestClient,
) -> None:
    case_id = client.post("/cases", json={"student": {}}).json()["case_id"]
    endpoint = f"/cases/{case_id}/evidence?include_receipt=true"
    form = {"kind": "document", "request_id": str(uuid4())}
    first = client.post(endpoint, data=form, files={"file": ("notes.txt", b"First version")}).json()
    second = client.post(
        endpoint, data=form, files={"file": ("notes.txt", b"Second version")}
    ).json()
    assert first["evidence_id"] != second["evidence_id"]
    assert len(second["case"]["evidence"]) == 2


def test_receipt_is_opt_in_and_malformed_retry_ids_are_rejected(client: TestClient) -> None:
    case_id = client.post("/cases", json={"student": {}}).json()["case_id"]
    endpoint = f"/cases/{case_id}/evidence"
    original = client.post(endpoint, data={"kind": "document", "text": "A note"})
    assert original.status_code == 200
    assert original.json()["case_id"] == case_id
    assert "case" not in original.json()
    invalid = client.post(
        endpoint, data={"kind": "document", "text": "x", "request_id": "not-a-uuid"}
    )
    assert invalid.status_code == 422


def test_initial_manifest_blocks_decision_until_files_are_uploaded_or_explicitly_skipped(
    client: TestClient,
) -> None:
    request_id, skipped_id = str(uuid4()), str(uuid4())
    items = [
        {"request_id": request_id, "kind": "email", "filename": "email.txt", "size": 5},
        {"request_id": skipped_id, "kind": "contract", "filename": "contract.pdf", "size": 0},
    ]
    case_id = client.post("/cases", json={"initial_uploads": items}).json()["case_id"]
    assert [u["state"] for u in client.get(f"/cases/{case_id}/uploads").json()] == [
        "pending",
        "pending",
    ]
    blocked = client.post(f"/cases/{case_id}/decide")
    assert blocked.status_code == 409 and "Continue without this file" in blocked.json()["detail"]
    accepted = client.post(
        f"/cases/{case_id}/evidence?include_receipt=true",
        data={"kind": "email", "request_id": request_id},
        files={"file": ("email.txt", b"Hello")},
    )
    assert accepted.status_code == 200 and accepted.json()["read_error"] is None
    assert client.portal
    client.portal.call(client.app.state.service.wait_idle)  # type: ignore[attr-defined]
    assert client.get(f"/cases/{case_id}").json()["status"] == "open"
    assert client.post(f"/cases/{case_id}/decide").status_code == 409
    skipped = client.post(f"/cases/{case_id}/uploads/{skipped_id}/skip")
    assert skipped.status_code == 200
    assert [u["state"] for u in skipped.json()] == ["accepted", "skipped"]
    client.portal.call(client.app.state.service.wait_idle)  # type: ignore[attr-defined]
    assert client.post(f"/cases/{case_id}/decide").json()["status"] == "decided"
    assert client.post(f"/cases/{case_id}/uploads/{skipped_id}/skip").status_code == 200


def test_manifest_rejects_duplicate_ids_and_unknown_files(client: TestClient) -> None:
    item = {"request_id": str(uuid4()), "kind": "email", "filename": "x.txt", "size": 1}
    assert client.post("/cases", json={"initial_uploads": [item, item]}).status_code == 422
    case_id = client.post("/cases", json={"initial_uploads": [item]}).json()["case_id"]
    assert client.post(f"/cases/{case_id}/uploads/{uuid4()}/skip").status_code == 404
    assert client.get("/cases/missing/uploads").status_code == 404
