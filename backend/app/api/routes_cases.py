"""REST routes for cases."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.schemas import DebriefRequest, EvidenceReceipt, OpenCaseRequest, ReplyRequest
from app.contracts import Case, Decision, EvidenceKind
from app.orchestrator.debrief import CallAnswer, CallDebrief, CallLine
from app.orchestrator.service import CaseService, Upload
from app.storage.repository import InitialUpload

router = APIRouter()


def _service(request: Request) -> CaseService:
    return request.app.state.service


@router.post("/cases")
async def open_case(body: OpenCaseRequest, request: Request) -> Case:
    """Open a case at score 100 with all checks unverified."""
    return await _service(request).open_case(
        body.student,
        body.listing,
        body.landlord,
        initial_uploads=[
            InitialUpload.model_validate(u.model_dump(mode="json")) for u in body.initial_uploads
        ],
    )


@router.get("/cases/{case_id}/uploads")
async def uploads(case_id: str, request: Request) -> list[InitialUpload]:
    """Read initial attachment progress, including unfinished uploads after a reload."""
    return await _service(request).get_uploads(case_id)


@router.post("/cases/{case_id}/uploads/{request_id}/skip")
async def skip_upload(case_id: str, request_id: UUID, request: Request) -> list[InitialUpload]:
    """Explicitly continue without one initial file; never marks a check as cleared."""
    return await _service(request).skip_upload(case_id, str(request_id))


@router.post("/cases/{case_id}/evidence")
async def add_evidence(
    case_id: str,
    request: Request,
    kind: Annotated[EvidenceKind, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    student_name: Annotated[str | None, Form()] = None,
    request_id: Annotated[UUID | None, Form()] = None,
    retry_read: Annotated[bool, Form()] = False,
    include_receipt: bool = False,
) -> Case | EvidenceReceipt:
    """Upload a file or paste text (exactly one of the two), then analyse."""
    if (file is None) == (not text):
        raise HTTPException(422, "send exactly one of `file` and `text`")
    if file is not None:
        upload = Upload(
            kind,
            await file.read(),
            file.filename,
            note,
            student_name,
            str(request_id) if request_id else None,
            retry_read,
        )
    else:
        upload = Upload(
            kind,
            (text or "").encode(),
            None,
            note,
            student_name,
            str(request_id) if request_id else None,
            retry_read,
        )
    result = await _service(request).accept_evidence(case_id, upload)
    if include_receipt:
        return EvidenceReceipt(
            case=result.case,
            evidence_id=result.evidence_id,
            read_error=result.read_error,
        )
    return result.case


@router.post("/cases/{case_id}/messages")
async def reply(case_id: str, body: ReplyRequest, request: Request) -> Case:
    """The student answers the orchestrator, optionally targeting one action by id."""
    return await _service(request).reply(
        case_id, body.text, body.evidence_ids, body.action_id, body.status
    )


def _utc(at: datetime | None) -> datetime | None:
    """A call time in UTC; a time without a zone is taken as UTC."""
    if at is None:
        return None
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


@router.post("/cases/{case_id}/debrief")
async def debrief(case_id: str, body: DebriefRequest, request: Request) -> Case:
    """A voice call ended: save its transcript, apply what it answered, then analyse.

    Returns the case at once; the analysis follows over the stream. An answer for an unknown
    or closed action is dropped with a note (the call already happened), not a 422.
    """
    now = datetime.now(UTC)
    call = CallDebrief(
        lines=tuple(CallLine(line.role, line.text, _utc(line.at) or now) for line in body.lines),
        answers=tuple(CallAnswer(a.action_id, a.answer, a.status) for a in body.answers),
        started_at=body.started_at,
        source=body.source,
    )
    return await _service(request).debrief(case_id, call)


@router.post("/cases/{case_id}/decide")
async def decide(case_id: str, request: Request) -> Case:
    """The live assessment on what is verified so far. The case stays open: nothing is final."""
    return await _service(request).decide(case_id)


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request) -> Case:
    """The full case."""
    return await _service(request).get_case(case_id)


@router.get("/cases/{case_id}/decision")
async def get_decision(case_id: str, request: Request) -> Decision:
    """The live assessment, or 404 before the first analysis round."""
    case = await _service(request).get_case(case_id)
    if case.decision is None:
        raise HTTPException(404, "no assessment yet")
    return case.decision
