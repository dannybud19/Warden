"""`POST /cases/{id}/debrief` over HTTP (TestClient, no network)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.contracts import Case, EvidenceKind
from app.core.settings import Settings
from app.intake import service as intake_service
from app.orchestrator import debrief
from tests.conftest import EmptyAgent

LINES = [
    {"role": "orchestrator", "text": "Tell me what happened.", "at": "2026-11-15T03:30:00Z"},
    {"role": "student", "text": "They asked for a deposit first.", "at": "2026-11-15T03:31:00Z"},
    {"role": "orchestrator", "text": "Did you pay?", "at": "2026-11-15T03:32:00Z"},
    {"role": "student", "text": "Not yet, they want it today.", "at": "2026-11-15T03:33:00Z"},
]
CHAT = (
    "[12/11/2026, 18:02:11] Sam: Is the flat available?\n"
    "[12/11/2026, 18:14:02] Mark Evans: Three other students want it. Send the deposit today.\n"
)


@pytest.fixture
def client(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(intake_service, "UPLOADS_DIR", tmp_path / ".uploads")
    with TestClient(create_app(settings)) as c:
        c.app.state.service.agents = [EmptyAgent()]  # type: ignore[attr-defined]
        yield c


def _settle(client: TestClient) -> None:
    assert client.portal is not None
    client.portal.call(client.app.state.service.wait_idle)  # type: ignore[attr-defined]


def _open(client: TestClient) -> str:
    response = client.post(
        "/cases",
        json={
            "student": {"budget_pcm": 1100},
            "listing": {"address": "Flat 3, 12 Elm Road, London W12 8QT", "rent_pcm": 850},
            "landlord": {"name": "Mark Evans"},
        },
    )
    assert response.status_code == 200
    return Case.model_validate(response.json()).case_id


def test_a_debrief_returns_the_case_and_a_later_get_shows_the_call_in_the_chat(
    client: TestClient,
) -> None:
    case_id = _open(client)

    response = client.post(f"/cases/{case_id}/debrief", json={"source": "call", "lines": LINES})
    assert response.status_code == 200
    body = Case.model_validate(response.json())
    assert body.case_id == case_id
    (recording,) = [e for e in body.evidence if e.kind == EvidenceKind.CALL_RECORDING]
    assert "[03:31] You: They asked for a deposit first." in (recording.extracted_text or "")
    _settle(client)

    stored = Case.model_validate(client.get(f"/cases/{case_id}").json())
    texts = [t.text for t in stored.chat]
    assert texts[:5] == [*[line["text"] for line in LINES], debrief.THANKS_TEXT]
    assert [t.role for t in stored.chat[:4]] == ["orchestrator", "student"] * 2
    assert [m.channel for m in stored.messages] == ["call", "call"]


def test_a_debrief_answers_an_open_action_and_drops_unknown_ones_without_a_422(
    client: TestClient,
) -> None:
    case_id = _open(client)
    client.post(
        f"/cases/{case_id}/evidence",
        data={"kind": "chat_export", "text": CHAT, "student_name": "Sam"},
    )
    _settle(client)
    actions = client.get(f"/cases/{case_id}").json()["actions"]
    open_id = next(a["id"] for a in actions if a["status"] == "open")

    response = client.post(
        f"/cases/{case_id}/debrief",
        json={
            "lines": LINES,
            "answers": [
                {"action_id": open_id, "answer": "no thanks", "status": "skipped"},
                {"action_id": "act_does_not_exist", "answer": "hello"},
            ],
        },
    )
    assert response.status_code == 200
    by_id = {a["id"]: a for a in response.json()["actions"]}
    assert by_id[open_id]["status"] == "skipped" and by_id[open_id]["answer"] == "no thanks"
    _settle(client)


def test_a_debrief_for_a_decided_case_is_409(client: TestClient) -> None:
    case_id = _open(client)
    assert client.post(f"/cases/{case_id}/decide").status_code == 200
    response = client.post(f"/cases/{case_id}/debrief", json={"lines": LINES})
    assert response.status_code == 409
    assert Case.model_validate(client.get(f"/cases/{case_id}").json()).evidence == []


def test_a_debrief_for_an_unknown_case_is_404(client: TestClient) -> None:
    assert client.post("/cases/case_nope/debrief", json={"lines": LINES}).status_code == 404


def test_empty_lines_are_422(client: TestClient) -> None:
    case_id = _open(client)
    assert client.post(f"/cases/{case_id}/debrief", json={"lines": []}).status_code == 422
    assert client.post(f"/cases/{case_id}/debrief", json={}).status_code == 422


def test_lines_that_are_all_blank_are_422(client: TestClient) -> None:
    case_id = _open(client)
    blank = [{"role": "student", "text": "   "}, {"role": "orchestrator", "text": ""}]
    assert client.post(f"/cases/{case_id}/debrief", json={"lines": blank}).status_code == 422
    stored = Case.model_validate(client.get(f"/cases/{case_id}").json())
    assert stored.evidence == [] and stored.chat == []


def test_a_bad_role_or_status_is_422(client: TestClient) -> None:
    case_id = _open(client)
    url = f"/cases/{case_id}/debrief"
    assert client.post(url, json={"lines": [{"role": "robot", "text": "hi"}]}).status_code == 422
    bad = {"action_id": "a", "answer": "x", "status": "maybe"}
    assert client.post(url, json={"lines": LINES, "answers": [bad]}).status_code == 422


def test_a_bank_account_in_a_debrief_is_masked_in_the_stored_case(client: TestClient) -> None:
    case_id = _open(client)
    lines = [{"role": "student", "text": "I sent it to account 12345678, call 07700 900123"}]
    response = client.post(f"/cases/{case_id}/debrief", json={"lines": lines})
    assert response.status_code == 200
    _settle(client)
    raw = client.get(f"/cases/{case_id}").text
    assert "12345678" not in raw and "07700 900123" in raw
