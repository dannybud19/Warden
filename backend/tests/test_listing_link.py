"""Opening a case with a listing link fills the listing and landlord from the page."""

from dataclasses import replace

import httpx
import pytest

from app.aggregators.listing_reader import reader
from app.aggregators.scoring.scoring import load_weights
from app.contracts import Landlord, Listing, StudentContext
from app.core.agent import AgentContext
from app.core.settings import Settings
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseService
from app.storage.memory import InMemoryCaseRepo

URL = "https://www.rightmove.co.uk/properties/123456789"
PAGE = """<html><head><title>2 bedroom flat to rent in Elm Road, London, W12</title>
<script type="application/ld+json">{"@type": "Residence", "address": {"streetAddress":
"Flat 3, 12 Elm Road", "addressLocality": "London", "postalCode": "W12 8QT"}}</script></head>
<body><p>&pound;1,250 pcm</p><p>Deposit: &pound;1,442</p>
<p>Marketed by Prime City Lettings</p></body></html>"""


async def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _service(ctx: AgentContext, mode: str) -> CaseService:
    settings = Settings(_env_file=None, default_agent_mode=mode, storage="memory")  # type: ignore[call-arg]
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=PAGE))
    )
    return CaseService(
        InMemoryCaseRepo(),
        EventBus(),
        [],
        replace(ctx, settings=settings, http=http),
        load_weights(),
    )


async def test_link_fills_empty_fields_and_keeps_what_the_student_typed(
    ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reader, "resolve_host", _public)
    service = _service(ctx, "real")
    case = await service.open_case(
        StudentContext(), Listing(url=URL, rent_pcm=1100), Landlord(name="Mark Evans")
    )
    assert case.listing is not None and case.landlord is not None
    assert case.listing.rent_pcm == 1100  # typed by the student
    assert case.listing.deposit == 1442 and case.listing.platform == "Rightmove"
    assert case.listing.address == "Flat 3, 12 Elm Road, London, W12 8QT"
    assert case.landlord.name == "Mark Evans"
    assert case.landlord.company_name == "Prime City Lettings"
    assert case.score_history[-1].score == 100  # reading a listing never lowers the score
    assert (await service.get_case(case.case_id)).listing == case.listing


async def test_stub_mode_leaves_the_case_as_given(ctx: AgentContext) -> None:
    service = _service(ctx, "stub")
    case = await service.open_case(StudentContext(), Listing(url=URL), None)
    # no request is made; only the site name, which comes from the link itself, is added
    assert case.listing == Listing(url=URL, platform="Rightmove") and case.landlord is None
