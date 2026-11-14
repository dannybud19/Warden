"""REST routes for cases."""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.schemas import OpenCaseRequest, ReplyRequest
from app.contracts import Case, Decision, EvidenceKind
from app.orchestrator.service import CaseService, Upload

router = APIRouter()


def _service(request: Request) -> CaseService:
    return request.app.state.service


@router.post("/cases")
async def open_case(body: OpenCaseRequest, request: Request) -> Case:
    """Open a case at score 100 with all checks unverified."""
    return await _service(request).open_case(body.student, body.listing, body.landlord)


@router.post("/cases/{case_id}/evidence")
async def add_evidence(
    case_id: str,
    request: Request,
    kind: Annotated[EvidenceKind, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    student_name: Annotated[str | None, Form()] = None,
) -> Case:
    """Upload a file or paste text (exactly one of the two), then analyse."""
    if (file is None) == (not text):
        raise HTTPException(422, "send exactly one of `file` and `text`")
    if file is not None:
        upload = Upload(kind, await file.read(), file.filename, note, student_name)
    else:
        upload = Upload(kind, (text or "").encode(), None, note, student_name)
    return await _service(request).add_evidence(case_id, upload)


@router.post("/cases/{case_id}/messages")
async def reply(case_id: str, body: ReplyRequest, request: Request) -> Case:
    """The student answers the orchestrator, optionally targeting one action by id."""
    return await _service(request).reply(
        case_id, body.text, body.evidence_ids, body.action_id, body.status
    )


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request) -> Case:
    """The full case."""
    return await _service(request).get_case(case_id)


@router.get("/cases/{case_id}/decision")
async def get_decision(case_id: str, request: Request) -> Decision:
    """The final decision, or 404 while the case is still open."""
    case = await _service(request).get_case(case_id)
    if case.decision is None:
        raise HTTPException(404, "no decision yet")
    return case.decision
