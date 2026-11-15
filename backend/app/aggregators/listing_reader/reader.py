"""Listing reader: open the listing link a student gives and pull out the details it states.

`read_listing` fetches the page and returns `ListingDetails`. `apply_details` copies them into the
empty fields of `case.listing` and `case.landlord`; anything the student typed is never overwritten.
The orchestrator calls both when a case is opened with a link. Nothing here judges the listing.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from app.aggregators.listing_reader import rules
from app.aggregators.listing_reader.models import ListingDetails, LLMListing, Quoted
from app.contracts import Landlord, Listing
from app.core.agent import AgentContext

NAME = "listing_reader"  # `AGENT_MODE_LISTING_READER=real` switches the fetch on
LINKUP_FETCH_URL = "https://api.linkup.so/v1/fetch"
FETCH_TIMEOUT_S = 12.0
LINKUP_TIMEOUT_S = 25.0  # Linkup renders JavaScript, which takes longer
MAX_REDIRECTS = 3
MAX_PAGE_CHARS = 1_500_000
MAX_LLM_CHARS = 12_000
USER_AGENT = "Mozilla/5.0 (compatible; WardenListingReader/0.1; student rental safety check)"

Resolver = Callable[[str], Awaitable[list[str]]]


@lru_cache
def system_prompt() -> str:
    return (Path(__file__).parent / "prompts" / "extract.md").read_text(encoding="utf-8")


async def resolve_host(host: str) -> list[str]:
    """Every IP address `host` resolves to."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


async def _is_public_host(url: str, resolve: Resolver) -> bool:
    """True when every address the host resolves to is a public one."""
    host = urlsplit(url).hostname or ""
    try:
        addresses = await resolve(host)
    except OSError:
        return False
    return bool(addresses) and all(rules.is_public_ip(a) for a in addresses)


# ---------------------------------------------------------------- fetching


async def _fetch_linkup(url: str, ctx: AgentContext) -> tuple[str, str] | None:
    """The page through Linkup's fetch API as `(text, raw)`, or None when it fails."""
    response = await ctx.http.post(
        LINKUP_FETCH_URL,
        headers={"Authorization": f"Bearer {ctx.settings.linkup_api_key}"},
        json={"url": url, "renderJs": True},
        timeout=LINKUP_TIMEOUT_S,
    )
    if response.status_code != httpx.codes.OK:
        ctx.log.warning("listing_reader: linkup fetch returned %s", response.status_code)
        return None
    body = response.json()
    markdown = str(body.get("markdown") or body.get("content") or "")[:MAX_PAGE_CHARS]
    return (markdown, markdown) if markdown.strip() else None


async def _fetch_direct(url: str, ctx: AgentContext, resolve: Resolver) -> tuple[int, str] | None:
    """The page by a plain GET as `(status, html)`. Each redirect is checked like the first URL."""
    for _ in range(MAX_REDIRECTS + 1):
        if not await _is_public_host(url, resolve):
            ctx.log.warning("listing_reader: refused a host that is not public")
            return None
        response = await ctx.http.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
            follow_redirects=False,
            timeout=FETCH_TIMEOUT_S,
        )
        if response.is_redirect and (target := response.headers.get("location")):
            next_url = rules.safe_url(urljoin(url, target))
            if next_url is None:
                return None
            url = next_url
            continue
        return response.status_code, response.text[:MAX_PAGE_CHARS]
    return None


# ---------------------------------------------------------------- the LLM pass


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _kept(item: Quoted | None, page: str) -> tuple[str, str] | None:
    """`(value, quote)` when the quote really is in the page, else None."""
    if item is None:
        return None
    value, quote = item.value.strip(), _squash(item.quote)
    if not value or not quote or quote not in page:
        return None
    return value, quote[: rules.MAX_QUOTE]


def _money(item: Quoted | None, page: str) -> tuple[int, str] | None:
    """A quoted amount, kept only when the same digits appear in its quote."""
    kept = _kept(item, page)
    if kept is None:
        return None
    amount = rules.parse_money(kept[0].lstrip("£ "))
    digits = re.sub(r"\D", "", re.sub(r"\.\d{1,2}\b", "", kept[1]))  # pence dropped
    return (amount, kept[1]) if amount and str(amount) in digits else None


def convert(output: LLMListing, text: str, url: str) -> ListingDetails:
    """The model's reading as `ListingDetails`, dropping every value its quote does not support."""
    page = _squash(text)
    details = ListingDetails(url=url, platform=rules.platform_of(url))
    quotes: dict[str, str] = {}

    if address := _kept(output.address, page):
        details.address, quotes["address"] = address
    if rent := _money(output.rent, page):
        details.rent_pcm, quotes["rent_pcm"] = rules.to_pcm(rent[0], output.rent_period), rent[1]
    if deposit := _money(output.deposit, page):
        details.deposit, quotes["deposit"] = deposit
    if (agency := _kept(output.agency_name, page)) and agency[0] != details.platform:
        details.agency_name, quotes["agency_name"] = agency
    if number := _kept(output.company_number, page):
        cleaned = re.sub(r"\s", "", number[0]).upper()
        if re.fullmatch(r"(?:[A-Z]{2})?\d{6,8}", cleaned) and cleaned in number[1].replace(" ", ""):
            details.company_number, quotes["company_number"] = cleaned, number[1]
    if (landlord := _kept(output.landlord_name, page)) and len(landlord[0].split()) >= 2:
        details.landlord_name, quotes["landlord_name"] = landlord
    summary = rules.html_to_text(output.summary)[: rules.MAX_DESCRIPTION].strip()
    if summary:
        details.description = summary

    details.quotes = quotes
    return details


async def _llm_details(text: str, url: str, ctx: AgentContext) -> ListingDetails | None:
    try:
        output = await ctx.llm.complete_json(
            system_prompt(),
            f"<url>{url}</url>\n\n<page>\n{text[:MAX_LLM_CHARS]}\n</page>",
            LLMListing,
        )
    except Exception as exc:  # noqa: BLE001 - the pattern-based reading must still be returned
        ctx.log.warning("listing_reader: LLM pass failed, rules only (%r)", exc)
        return None
    return convert(output, text, url)


# ---------------------------------------------------------------- entry points


async def read_listing(
    url: str, ctx: AgentContext, *, resolve: Resolver | None = None
) -> ListingDetails:
    """Fetch the listing at `url` and return what it states. Never raises.

    Stub mode (the default) makes no request and returns `status="skipped"`. Linkup's fetch API is
    used when `LINKUP_API_KEY` is set (it renders JavaScript); otherwise, or if Linkup fails, the
    page is fetched directly. Sources, strongest first: the site's own structured data, the LLM
    (each value checked against the page), then patterns over the page text.
    """
    platform = rules.platform_of(url)
    if ctx.settings.agent_mode(NAME) != "real":
        return ListingDetails(url=url, status="skipped", platform=platform)
    checked = rules.safe_url(url)
    if checked is None:
        return ListingDetails(url=url, status="unsafe_url", platform=platform)

    try:
        text, raw, blocked = "", "", False
        via: Literal["linkup", "direct", ""] = ""
        if ctx.settings.linkup_api_key and (fetched := await _fetch_linkup(checked, ctx)):
            text, raw = fetched
            via = "linkup"
        if not text:
            direct = await _fetch_direct(checked, ctx, resolve or resolve_host)
            if direct is None:
                return ListingDetails(url=url, status="unreachable", platform=platform)
            status, raw = direct
            text, via = rules.html_to_text(raw), "direct"
            blocked = rules.looks_blocked(status, text)
            if not blocked and status >= httpx.codes.BAD_REQUEST:
                return ListingDetails(
                    url=url, status="unreachable", via="direct", platform=platform
                )
    except (httpx.HTTPError, ValueError) as exc:
        ctx.log.warning("listing_reader: could not fetch the listing (%r)", exc)
        return ListingDetails(url=url, status="unreachable", platform=platform)

    if blocked:
        return ListingDetails(url=url, status="blocked", via="direct", platform=platform)
    if not text.strip():
        return ListingDetails(url=url, status="empty", via=via, platform=platform)

    layers = [rules.structured_details(raw, url)]
    if llm := await _llm_details(text, url, ctx):
        layers.append(llm)
    layers.append(rules.text_details(text, url))
    details = rules.merge(*layers)
    details.via = via
    details.status = "ok" if details.found() else "empty"
    return details


def apply_details(
    listing: Listing | None, landlord: Landlord | None, details: ListingDetails
) -> tuple[Listing | None, Landlord | None]:
    """Copy the page's details into the empty fields of the listing and landlord.

    What the student typed always wins. The address is filled only when the page gives a full
    postcode: the crosscheck compares the listing address with the contract's, and a partial
    address ("Elm Road, London W12") would look like a mismatch. A partial one goes in the
    description instead.
    """
    if details.status != "ok":
        if listing and details.platform and not listing.platform:
            listing = listing.model_copy(update={"platform": details.platform})
        return listing, landlord

    listing = listing or Listing(url=details.url)
    _, full_postcode = rules.split_postcode(details.address or "")
    description = details.description
    if details.address and not full_postcode and details.address not in (description or ""):
        description = f"{description or ''} (listed at: {details.address})".strip()
    page_listing = {
        "platform": details.platform,
        "address": details.address if full_postcode else None,
        "postcode": details.postcode,
        "rent_pcm": details.rent_pcm,
        "deposit": details.deposit,
        "description": description,
    }
    updates = {k: v for k, v in page_listing.items() if v is not None and not getattr(listing, k)}
    listing = listing.model_copy(update=updates)

    page_landlord = {
        "company_name": details.agency_name,
        "company_number": details.company_number,
        "name": details.landlord_name,
    }
    current = landlord or Landlord()
    updates = {k: v for k, v in page_landlord.items() if v is not None and not getattr(current, k)}
    if updates:
        landlord = current.model_copy(update=updates)
    return listing, landlord


def summary_message(details: ListingDetails) -> str | None:
    """One plain line for the student about what the link gave us. None in stub mode."""
    site = details.platform or "the listing"
    match details.status:
        case "skipped":
            return None
        case "ok":
            parts = []
            if details.agency_name:
                parts.append(f"advertised by {details.agency_name}")
            if details.rent_pcm:
                parts.append(f"rent £{details.rent_pcm:,} a month")
            if details.deposit:
                parts.append(f"deposit £{details.deposit:,}")
            if details.address or details.postcode:
                parts.append(f"at {details.address or details.postcode}")
            found = ", ".join(parts) or "some details"
            return f"I read the {site} page: {found}. Check these match what you were told."
        case "blocked":
            return (
                f"{site} would not let me open the link. Paste the listing text or type the "
                "address, rent and agency name instead."
            )
        case "unsafe_url":
            return "That link is not a public web page, so I did not open it."
        case _:
            return "I could not read anything useful from the listing link. Is the link still live?"
