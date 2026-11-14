"""API smoke tests (TestClient, no network)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.main import create_app
from app.contracts import Case
from app.core.settings import Settings
from app.intake import service as intake_service
from tests.conftest import EmptyAgent

CHAT = (
    "[12/11/2026, 18:02:11] Sam: Is the flat available?\n"
    "[12/11/2026, 18:14:02] Mark Evans: Three other students want it. Send the deposit today.\n"
)


@pytest.fixture
def client(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(intake_service, "UPLOADS_DIR", tmp_path / ".uploads")  # keep repo clean
    with TestClient(create_app(settings)) as c:
        yield c


def _open(client: TestClient) -> str:
    response = client.post(
        "/cases",
        json={
            "student": {"budget_pcm": 1100},
            "listing": {"address": "Flat 3, 12 Elm Road, London W12 8QT", "rent_pcm": 850},
            "landlord": {"name": "Mark Evans", "company_name": "Prime City Lettings Ltd"},
        },
    )
    assert response.status_code == 200
    case = Case.model_validate(response.json())
    assert case.score_history[0].score == 100 and len(case.checks) == 8
    return case.case_id


def test_open_get_and_missing(client: TestClient) -> None:
    case_id = _open(client)
    assert client.get(f"/cases/{case_id}").json()["case_id"] == case_id
    assert client.get("/cases/case_nope").status_code == 404
    assert client.get(f"/cases/{case_id}/decision").status_code == 404
    assert client.post("/cases/case_nope/messages", json={"text": "hi"}).status_code == 404


def test_pasted_text_reply_and_decision_flow(client: TestClient) -> None:
    client.app.state.service.agents = [EmptyAgent()]  # type: ignore[attr-defined]
    case_id = _open(client)

    response = client.post(
        f"/cases/{case_id}/evidence",
        data={"kind": "chat_export", "text": CHAT, "student_name": "Sam", "note": "chat"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["messages"]) == 2 and body["messages"][1]["sender"] == "agent"
    assert len(body["actions"]) == 3 and body["status"] == "open"

    for _ in range(4):
        response = client.post(f"/cases/{case_id}/messages", json={"text": "yes"})
        assert response.status_code == 200
    assert response.json()["status"] == "decided"

    decision = client.get(f"/cases/{case_id}/decision")
    assert decision.status_code == 200 and decision.json()["verdict"] == "not_verified"


def test_decided_case_returns_409(client: TestClient) -> None:
    case_id = _open(client)  # default stubs: the hard flags close the case on first upload
    response = client.post(
        f"/cases/{case_id}/evidence",
        data={"kind": "chat_export", "text": CHAT, "student_name": "Sam"},
    )
    assert response.json()["decision"]["verdict"] == "likely_scam"
    again = client.post(f"/cases/{case_id}/evidence", data={"kind": "email", "text": "hello"})
    assert again.status_code == 409
    assert client.post(f"/cases/{case_id}/messages", json={"text": "yes"}).status_code == 409


def test_file_upload_and_validation(client: TestClient) -> None:
    client.app.state.service.agents = [EmptyAgent()]  # type: ignore[attr-defined]
    case_id = _open(client)
    url = f"/cases/{case_id}/evidence"
    assert client.post(url, data={"kind": "email"}).status_code == 422  # neither
    both = client.post(url, data={"kind": "email", "text": "x"}, files={"file": ("a.txt", b"y")})
    assert both.status_code == 422
    assert client.post(url, data={"kind": "nonsense", "text": "x"}).status_code == 422
    assert client.post("/cases", json={"student": {"budget_pcm": "lots"}}).status_code == 422

    ok = client.post(url, data={"kind": "email"}, files={"file": ("mail.txt", b"Dear Sam")})
    assert ok.status_code == 200
    assert ok.json()["messages"][0]["channel"] == "email"
    assert ok.json()["evidence"][0]["file_url"].endswith("_mail.txt")


def test_websocket_stream(client: TestClient) -> None:
    case_id = _open(client)
    with client.websocket_connect(f"/cases/{case_id}/stream") as ws:
        first = ws.receive_json()
        assert first["type"] == "score_updated" and first["score"]["score"] == 100
        client.post(
            f"/cases/{case_id}/evidence",
            data={"kind": "chat_export", "text": CHAT, "student_name": "Sam"},
        )
        seen = []
        while not seen or seen[-1] != "decision_made":
            seen.append(ws.receive_json()["type"])
        assert "agent_started" in seen and "agent_finished" in seen


def test_websocket_unknown_case_is_rejected(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/cases/case_nope/stream"):
        pass
