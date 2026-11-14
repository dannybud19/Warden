import json
import logging
from collections.abc import Callable

import httpx
import pytest

from app.aggregators.listing_reader import rules
from app.aggregators.listing_reader.models import ListingDetails
from app.aggregators.listing_reader.reader import (
    LINKUP_FETCH_URL,
    apply_details,
    read_listing,
    summary_message,
)
from app.contracts import Landlord, Listing
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.core.search import FakeSearch
from app.core.settings import Settings

PROMPT_KEY = "rental listing page"  # appears in prompts/extract.md
URL = "https://www.rightmove.co.uk/properties/123456789"

RIGHTMOVE_PAGE = """<html><head>
<title>2 bedroom flat to rent in Elm Road, London, W12</title>
<meta property="og:title" content="2 bedroom flat to rent in Elm Road, London, W12" />
<script type="application/ld+json">{"@type": "Residence",
  "address": {"streetAddress": "Flat 3, 12 Elm Road", "addressLocality": "London",
              "postalCode": "W12 8QT"}}</script>
<script>window.PAGE_MODEL = {"propertyData": {"prices": {"primaryPrice": "\\u00a31,250 pcm"},
  "customer": {"branchDisplayName": "Prime City Lettings, Shepherd's Bush"}}}</script>
<style>.x { color: red }</style></head>
<body><h1>Elm Road, London, W12</h1>
<p>&pound;1,250 pcm</p><p>&pound;288 pw</p>
<div>Holding deposit: &pound;288</div><div>Deposit: &pound;1,442</div>
<p>MARKETED BY Prime City Lettings, Shepherd's Bush</p>
<p>Similar properties: &pound;2,000 pcm</p></body></html>"""

SPAREROOM_TEXT = """Double room in friendly house share
£185 pw
Bills included. Security deposit £400.
Advertised by Hannah Clarke - live out landlord
Mile End Road, London E1 4NS"""


async def public(_host: str) -> list[str]:
    return ["93.184.216.34"]


async def private(_host: str) -> list[str]:
    return ["10.0.0.5"]


def make_ctx(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    mode: str = "real",
    linkup_key: str = "",
    llm: FakeLLM | None = None,
) -> AgentContext:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        default_agent_mode=mode,
        storage="memory",
        linkup_api_key=linkup_key,
    )
    return AgentContext(
        llm=llm or FakeLLM(),
        search=FakeSearch(),
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        settings=settings,
        log=logging.getLogger("test"),
    )


def page(
    html: str = RIGHTMOVE_PAGE, status: int = 200
) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, text=html)


# ---------------------------------------------------------------- rules


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "https://intranet/x",
        "https://files.internal/x",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "https://user:pw@example.com/",
        "https://example.com:8443/x",
        "not a link",
    ],
)
def test_unsafe_urls_are_refused(url: str) -> None:
    assert rules.safe_url(url) is None


def test_public_urls_are_kept_and_platform_named() -> None:
    assert rules.safe_url(URL) == URL
    assert rules.platform_of(URL) == "Rightmove"
    assert rules.platform_of("https://spareroom.co.uk/flatshare/1") == "SpareRoom"
    assert rules.platform_of("https://example.com/flat") is None


def test_html_to_text_drops_scripts_and_decodes() -> None:
    text = rules.html_to_text(RIGHTMOVE_PAGE)
    assert "£1,250 pcm" in text and "PAGE_MODEL" not in text and "color: red" not in text


@pytest.mark.parametrize(
    ("raw", "pounds"), [("1,250.00", 1250), ("850", 850), ("0", None), ("999999", None)]
)
def test_parse_money(raw: str, pounds: int | None) -> None:
    assert rules.parse_money(raw) == pounds


def test_weekly_rent_becomes_monthly() -> None:
    assert rules.to_pcm(185, "week") == 802 and rules.to_pcm(850, "month") == 850


def test_structured_data_gives_address_rent_and_agency() -> None:
    details = rules.structured_details(RIGHTMOVE_PAGE, URL)
    assert details.address == "Flat 3, 12 Elm Road, London, W12 8QT"
    assert details.postcode == "W12 8QT"
    assert details.rent_pcm == 1250
    assert details.agency_name == "Prime City Lettings, Shepherd's Bush"
    assert details.platform == "Rightmove"
    assert details.description == "2 bedroom flat to rent in Elm Road, London, W12"


def test_text_patterns_read_weekly_rent_deposit_and_advertiser() -> None:
    details = rules.text_details(SPAREROOM_TEXT, "https://www.spareroom.co.uk/1")
    assert details.rent_pcm == 802 and details.quotes["rent_pcm"] == "£185 pw"
    assert details.deposit == 400
    assert details.agency_name == "Hannah Clarke"
    assert details.postcode is None  # never from loose text: see the test below


def test_postcode_is_the_property_not_the_agents_office() -> None:
    """Real pages carry the agent's office and the site's own address in the text."""
    page = """<html><head>
    <title>1 bedroom apartment for rent in Boardwalk Place, London, E14</title>
    <meta property="og:title" content="Check out this 1 bedroom apartment for rent on Rightmove" />
    </head><body><h1 itemprop="streetAddress">Boardwalk Place, London, E14</h1>
    <p>&pound;2,400 pcm</p><p>MARKETED BY</p><p>Savills Lettings, Canary Wharf</p>
    <p>20 Canada Square London E14 5NN</p><footer>Site Ltd, 20 Wenlock Road, N1 7GU</footer>
    </body></html>"""
    text = rules.html_to_text(page)
    details = rules.merge(rules.structured_details(page, URL), rules.text_details(text, URL))
    assert details.address == "Boardwalk Place, London, E14"
    assert details.postcode == "E14"
    assert details.description == "1 bedroom apartment for rent in Boardwalk Place, London, E14"
    assert details.rent_pcm == 2400

    titled = "<html><head><title>1 Bed Flat, London, WC2N - To Rent</title></head><body>x</body>"
    details = rules.merge(rules.structured_details(titled, URL), rules.text_details("x", URL))
    assert details.address is None and details.postcode == "WC2N"


def test_holding_deposit_is_not_the_deposit() -> None:
    details = rules.text_details(rules.html_to_text(RIGHTMOVE_PAGE), URL)
    assert details.deposit == 1442


def test_the_site_itself_is_never_the_agency() -> None:
    details = rules.text_details("Listed by Rightmove\n£900 pcm", URL)
    assert details.agency_name is None


# ---------------------------------------------------------------- reading a page


async def test_stub_mode_makes_no_request() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected in stub mode")

    details = await read_listing(URL, make_ctx(fail, mode="stub"), resolve=public)
    assert details.status == "skipped" and details.found() == []
    assert summary_message(details) is None


async def test_reads_a_page_directly() -> None:
    details = await read_listing(URL, make_ctx(page()), resolve=public)
    assert details.status == "ok" and details.via == "direct"
    assert (details.rent_pcm, details.deposit) == (1250, 1442)
    assert details.address == "Flat 3, 12 Elm Road, London, W12 8QT"
    assert details.agency_name == "Prime City Lettings, Shepherd's Bush"
    assert all(details.quotes[name] for name in ("address", "rent_pcm", "deposit", "agency_name"))
    assert "Prime City Lettings" in (summary_message(details) or "")


async def test_blocked_site_is_reported_not_guessed() -> None:
    details = await read_listing(URL, make_ctx(page("Access denied", 403)), resolve=public)
    assert details.status == "blocked" and details.found() == []
    assert "would not let me open" in (summary_message(details) or "")


async def test_missing_page_is_unreachable() -> None:
    details = await read_listing(URL, make_ctx(page("gone", 404)), resolve=public)
    assert details.status == "unreachable"


async def test_host_that_resolves_to_a_private_address_is_not_fetched() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch a private address")

    details = await read_listing(URL, make_ctx(fail), resolve=private)
    assert details.status == "unreachable"


async def test_redirect_to_a_private_address_is_not_followed() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.rightmove.co.uk"
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    details = await read_listing(URL, make_ctx(redirect), resolve=public)
    assert details.status == "unreachable"


async def test_unsafe_link_is_not_opened() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch")

    details = await read_listing("http://localhost:8000/cases", make_ctx(fail), resolve=public)
    assert details.status == "unsafe_url"
    assert "did not open it" in (summary_message(details) or "")


async def test_network_error_never_raises() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    details = await read_listing(URL, make_ctx(boom), resolve=public)
    assert details.status == "unreachable"


async def test_linkup_is_used_when_a_key_is_set() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert str(request.url) == LINKUP_FETCH_URL
        assert json.loads(request.content) == {"url": URL, "renderJs": True}
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"markdown": SPAREROOM_TEXT})

    details = await read_listing(URL, make_ctx(handler, linkup_key="test-key"), resolve=public)
    assert seen == [LINKUP_FETCH_URL]
    assert details.via == "linkup" and details.rent_pcm == 802 and details.deposit == 400


async def test_falls_back_to_a_direct_fetch_when_linkup_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LINKUP_FETCH_URL:
            return httpx.Response(500)
        return httpx.Response(200, text=RIGHTMOVE_PAGE)

    details = await read_listing(URL, make_ctx(handler, linkup_key="test-key"), resolve=public)
    assert details.via == "direct" and details.rent_pcm == 1250


# ---------------------------------------------------------------- LLM pass


async def test_llm_values_need_a_real_quote() -> None:
    text = (
        "Lovely studio near the park.\n"
        "Rent is 950 pounds each month, deposit 1,100.\n"
        "Contact Mr Tom Reed."
    )
    reply = {
        "address": {"value": "1 Fake Street, London", "quote": "this is not on the page"},
        "rent": {"value": "950", "quote": "Rent is 950 pounds each month"},
        "rent_period": "month",
        "deposit": {"value": "5000", "quote": "deposit 1,100"},  # digits do not match the quote
        "agency_name": {"value": "Rightmove", "quote": "Lovely studio"},  # the site, not an agency
        "landlord_name": {"value": "Tom Reed", "quote": "Contact Mr Tom Reed"},
        "summary": "A studio near the park.",
    }
    llm = FakeLLM({PROMPT_KEY: json.dumps(reply)})
    details = await read_listing(URL, make_ctx(page(text), llm=llm), resolve=public)
    assert details.rent_pcm == 950 and details.quotes["rent_pcm"] == "Rent is 950 pounds each month"
    assert details.landlord_name == "Tom Reed"
    assert details.address is None and details.deposit is None and details.agency_name is None
    assert details.description == "A studio near the park."


async def test_site_data_beats_the_llm_and_llm_failure_is_harmless() -> None:
    wrong = {"rent": {"value": "2000", "quote": "£2,000 pcm"}, "rent_period": "month"}
    llm = FakeLLM({PROMPT_KEY: json.dumps(wrong)})
    details = await read_listing(URL, make_ctx(page(), llm=llm), resolve=public)
    assert details.rent_pcm == 1250  # the "similar properties" price is ignored

    broken = FakeLLM({PROMPT_KEY: "not json"})
    details = await read_listing(URL, make_ctx(page(), llm=broken), resolve=public)
    assert details.status == "ok" and details.rent_pcm == 1250


# ---------------------------------------------------------------- applying to the case


def _details(**fields: object) -> ListingDetails:
    return ListingDetails.model_validate({"url": URL, "platform": "Rightmove", **fields})


def test_page_fills_only_the_empty_fields() -> None:
    listing = Listing(url=URL, rent_pcm=1100)
    landlord = Landlord(company_name="What Sam Typed Ltd")
    details = _details(
        address="Flat 3, 12 Elm Road, London W12 8QT",
        postcode="W12 8QT",
        rent_pcm=1250,
        deposit=1442,
        agency_name="Prime City Lettings",
        company_number="12345678",
    )
    new_listing, new_landlord = apply_details(listing, landlord, details)
    assert new_listing is not None and new_landlord is not None
    assert new_listing.rent_pcm == 1100  # what the student typed wins
    assert new_listing.deposit == 1442 and new_listing.platform == "Rightmove"
    assert new_listing.address == "Flat 3, 12 Elm Road, London W12 8QT"
    assert new_landlord.company_name == "What Sam Typed Ltd"
    assert new_landlord.company_number == "12345678"


def test_partial_address_goes_to_the_description_not_the_address() -> None:
    details = _details(address="Elm Road, London, W12", postcode="W12", description="2 bed flat")
    listing, landlord = apply_details(Listing(url=URL), None, details)
    assert listing is not None and landlord is None
    assert listing.address is None and listing.postcode == "W12"
    assert listing.description == "2 bed flat (listed at: Elm Road, London, W12)"


def test_failed_read_changes_nothing_but_the_platform() -> None:
    listing, landlord = apply_details(Listing(url=URL), None, _details(status="blocked"))
    assert listing == Listing(url=URL, platform="Rightmove") and landlord is None
