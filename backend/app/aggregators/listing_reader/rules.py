"""Pure functions: URL safety, HTML to text, and the details a listing page states outright."""

import html as html_lib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

from app.aggregators.listing_reader.models import ListingDetails

_I = re.IGNORECASE
MAX_QUOTE = 200
MAX_DESCRIPTION = 200

# The site a link belongs to. These are marketplaces, never the letting agency.
PLATFORMS = {
    "rightmove.co.uk": "Rightmove",
    "zoopla.co.uk": "Zoopla",
    "spareroom.co.uk": "SpareRoom",
    "openrent.co.uk": "OpenRent",
    "onthemarket.com": "OnTheMarket",
    "primelocation.com": "PrimeLocation",
    "gumtree.com": "Gumtree",
    "facebook.com": "Facebook Marketplace",
    "unihomes.co.uk": "UniHomes",
    "accommodationforstudents.com": "Accommodation for Students",
    "student.com": "Student.com",
    "airbnb.co.uk": "Airbnb",
    "airbnb.com": "Airbnb",
    "booking.com": "Booking.com",
}

_BLOCKED_HOSTS = ("localhost",)
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp")

_MONEY = r"£\s?(\d[\d,]*(?:\.\d{1,2})?)"
_RENT_PCM = re.compile(
    _MONEY + r"\s*(?:pcm\b|p\.c\.m\.?|per\s+calendar\s+month|per\s+month|/\s?month|a\s+month|"
    r"pm\b|p/m\b|/\s?mo\b|monthly)",
    _I,
)
_RENT_PW = re.compile(
    _MONEY + r"\s*(?:pw\b|p\.w\.?|pppw\b|per\s+week|/\s?week|a\s+week|p/w\b|weekly)", _I
)
_DEPOSIT = re.compile(r"\bdeposit\b[^£\n]{0,30}" + _MONEY, _I)
_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s?(\d[A-Z]{2})\b")
_DISTRICT = re.compile(r"\b((?:E|EC|N|NW|SE|SW|W|WC)\d{1,2}[A-Z]?)\b")
_AGENCY = re.compile(
    r"\b(?:marketed by|listed by|advertised by|let by|letting agent|offered by)\b\s*:?\s*"
    r"([A-Z][\w&'’.\- ]{1,60}?)\s*(?=[,|\n(]|\s-\s|$)",
    _I,
)
_COMPANY_NUMBER = re.compile(
    r"\b(?:company|registration|registered)\s*(?:number|no\.?|num\.?)\s*:?\s*"
    r"((?:[A-Z]{2})?\d{6,8})\b",
    _I,
)
_BLOCK_WORDS = re.compile(
    r"captcha|access denied|are you a robot|verify you are (?:a )?human|just a moment|"
    r"unusual traffic|enable javascript and cookies",
    _I,
)

_JSON_LD = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", _I | re.DOTALL
)
_META = re.compile(
    r"<meta[^>]*?(?:property|name)=[\"']([^\"']+)[\"'][^>]*?content=[\"']([^\"']*)[\"']", _I
)
_ITEMPROP_ADDRESS = re.compile(r"itemprop=[\"']streetAddress[\"'][^>]*>\s*([^<]{3,200}?)\s*<", _I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", _I | re.DOTALL)
_DROP_BLOCKS = re.compile(r"<(script|style|noscript|svg|template)\b.*?</\1\s*>", _I | re.DOTALL)
_LINE_BREAKS = re.compile(r"<\s*(?:br|/p|/div|/li|/tr|/h[1-6]|/section|/article)\b[^>]*>", _I)
_TAGS = re.compile(r"<[^>]+>")

# Keys that listing sites use in the JSON they embed in the page (Rightmove, Zoopla, Next.js apps).
_EMBEDDED_KEYS = {
    "address": ("displayAddress", "streetAddress", "fullAddress"),
    "agency_name": ("branchDisplayName", "companyTradingName", "companyName", "agentName"),
    "rent_text": ("primaryPrice", "displayPrice", "rentLabel"),
}


# ---------------------------------------------------------------- URL


def platform_of(url: str) -> str | None:
    """The marketplace a link belongs to, e.g. `Rightmove`. None for an unknown site."""
    host = (urlsplit(url).hostname or "").lower()
    for domain, name in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def is_public_ip(address: str) -> bool:
    """False for loopback, private, link-local and other non-public addresses."""
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def safe_url(url: str) -> str | None:
    """`url` if it is a plain public http(s) link, else None.

    The link comes from the student and the server fetches it, so anything that could point at
    the server's own network (localhost, private IPs, internal names, odd ports) is refused.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return None
    if port not in (None, 80, 443):
        return None
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
        return None
    if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host) and not is_public_ip(host.strip("[]")):
        return None
    return parts.geturl()


# ---------------------------------------------------------------- HTML


def html_to_text(page: str) -> str:
    """Readable text of an HTML page: scripts and tags removed, one block per line."""
    page = _DROP_BLOCKS.sub(" ", page)
    page = _LINE_BREAKS.sub("\n", page)
    page = html_lib.unescape(_TAGS.sub(" ", page))
    lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in page.split("\n"))
    return "\n".join(line for line in lines if line)


def looks_blocked(status: int, text: str) -> bool:
    """True when the site refused the request or served a bot check instead of the page."""
    if status in (401, 403, 429, 503):
        return True
    return len(text) < 1500 and bool(_BLOCK_WORDS.search(text))


def parse_money(raw: str) -> int | None:
    """`"1,250.00"` to `1250` (whole pounds). None when it is not a sensible amount."""
    try:
        amount = round(float(raw.replace(",", "")))
    except ValueError:
        return None
    return amount if 0 < amount < 100_000 else None


def to_pcm(amount: int, period: str) -> int:
    """A weekly rent as a monthly one (52 weeks over 12 months); monthly is returned as is."""
    return round(amount * 52 / 12) if period == "week" else amount


def _snippet(text: str, start: int, end: int) -> str:
    return text[start:end].strip()[:MAX_QUOTE]


def split_postcode(text: str) -> tuple[str | None, bool]:
    """The postcode in `text` and if it is full: `("W12 8QT", True)` or `("W12", False)`."""
    full = _POSTCODE.search(text.upper())
    if full:
        return f"{full.group(1)} {full.group(2)}", True
    district = _DISTRICT.search(text.upper())
    return (district.group(1), False) if district else (None, False)


# ---------------------------------------------------------------- structured data in the page


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every JSON object inside `node`, depth first."""
    if isinstance(node, dict):
        found = [node]
        for value in node.values():
            found.extend(_walk(value))
        return found
    if isinstance(node, list):
        return [item for value in node for item in _walk(value)]
    return []


def _json_ld(page: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for block in _JSON_LD.findall(page):
        try:
            objects.extend(_walk(json.loads(html_lib.unescape(block.strip()))))
        except ValueError:
            continue
    return objects


def _address_from_ld(node: dict[str, Any]) -> str | None:
    address = node.get("address")
    if isinstance(address, str):
        return address.strip() or None
    if isinstance(address, dict):
        parts = [
            str(address.get(key, "")).strip()
            for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode")
        ]
        return ", ".join(dict.fromkeys(p for p in parts if p)) or None
    return None


def _embedded(page: str, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.){{1,200}})"', page)
        if match:
            try:
                return str(json.loads(f'"{match.group(1)}"')).strip() or None
            except ValueError:
                continue
    return None


def structured_details(page: str, url: str) -> ListingDetails:
    """Details from machine-readable data in the HTML: JSON-LD, embedded JSON and meta tags.

    These are the site's own data fields, so they are trusted ahead of anything read from the text.
    """
    details = ListingDetails(url=url, platform=platform_of(url))
    quotes: dict[str, str] = {}

    def put(name: str, value: Any, quote: str) -> None:
        if value and getattr(details, name) is None:
            setattr(details, name, value)
            quotes[name] = quote[:MAX_QUOTE]

    for node in _json_ld(page):
        if address := _address_from_ld(node):
            put("address", address, address)
        offers = node.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict) and (price := parse_money(str(offer.get("price", "")))):
            unit = json.dumps(offer).lower()
            period = "week" if "week" in unit else "month"
            put("rent_pcm", to_pcm(price, period), f"£{offer.get('price')}")
        for key in ("seller", "provider", "broker", "offeredBy"):
            who = node.get(key)
            if isinstance(who, dict) and isinstance(who.get("name"), str):
                put("agency_name", who["name"].strip(), who["name"].strip())

    if address := _embedded(page, _EMBEDDED_KEYS["address"]):
        put("address", address, address)
    if marked := _ITEMPROP_ADDRESS.search(page):
        address = html_lib.unescape(marked.group(1)).strip()
        put("address", address, address)
    if agency := _embedded(page, _EMBEDDED_KEYS["agency_name"]):
        put("agency_name", agency, agency)
    if rent_text := _embedded(page, _EMBEDDED_KEYS["rent_text"]):
        rent, quote = _rent_in(rent_text)
        put("rent_pcm", rent, quote or rent_text)

    meta = {name.lower(): html_lib.unescape(content) for name, content in _META.findall(page)}
    title = _TITLE.search(page)
    # the page title names the property; `og:title` is often generic share text
    heading = (html_lib.unescape(title.group(1)) if title else "") or meta.get("og:title", "")
    heading = re.sub(r"\s+", " ", heading).strip()
    if heading:
        put("description", heading[:MAX_DESCRIPTION], heading)

    if details.agency_name and details.agency_name == details.platform:
        details.agency_name = None
        quotes.pop("agency_name", None)
    details.quotes = quotes
    return _with_postcode(details)


# ---------------------------------------------------------------- plain text


def _rent_in(text: str) -> tuple[int | None, str]:
    """The first rent in `text` as pounds per month, with the words it came from."""
    monthly = _RENT_PCM.search(text)
    if monthly and (amount := parse_money(monthly.group(1))):
        return amount, _snippet(text, monthly.start(), monthly.end())
    weekly = _RENT_PW.search(text)
    if weekly and (amount := parse_money(weekly.group(1))):
        return to_pcm(amount, "week"), _snippet(text, weekly.start(), weekly.end())
    return None, ""


def text_details(text: str, url: str) -> ListingDetails:
    """Details read from the page text with patterns. The weakest source: used to fill gaps only."""
    details = ListingDetails(url=url, platform=platform_of(url))
    quotes: dict[str, str] = {}

    rent, quote = _rent_in(text)
    if rent:
        details.rent_pcm, quotes["rent_pcm"] = rent, quote

    for match in _DEPOSIT.finditer(text):
        before = text[max(0, match.start() - 10) : match.start()].lower()
        if "holding" in before:  # a holding deposit is a different, smaller payment
            continue
        if amount := parse_money(match.group(1)):
            details.deposit = amount
            quotes["deposit"] = _snippet(text, match.start(), match.end())
            break

    if agency := _AGENCY.search(text):
        name = agency.group(1).strip(" .,-")
        if name and name != details.platform:
            details.agency_name = name
            quotes["agency_name"] = _snippet(text, agency.start(), agency.end())

    if number := _COMPANY_NUMBER.search(text):
        details.company_number = number.group(1).upper()
        quotes["company_number"] = _snippet(text, number.start(), number.end())

    # NOTE: no postcode is taken from loose text. The first one on a real page is usually the
    # agent's office or the website's own address, not the property (seen on Rightmove, OpenRent).
    details.quotes = quotes
    return details


# ---------------------------------------------------------------- combining


def _with_postcode(details: ListingDetails) -> ListingDetails:
    """Take the postcode from the address when the address has one."""
    if details.address and not details.postcode:
        postcode, _ = split_postcode(details.address)
        if postcode:
            details.postcode = postcode
            details.quotes = {**details.quotes, "postcode": details.address[:MAX_QUOTE]}
    return details


def merge(*layers: ListingDetails) -> ListingDetails:
    """One result from several readings of the same page: the first layer with a value wins."""
    first = layers[0]
    merged = ListingDetails(url=first.url, status=first.status, via=first.via)
    quotes: dict[str, str] = {}
    for name in ("platform", "address", "rent_pcm", "deposit", "agency_name", "company_number",
                 "landlord_name", "description"):  # fmt: skip
        for layer in layers:
            value = getattr(layer, name)
            if value is not None:
                setattr(merged, name, value)
                if name in layer.quotes:
                    quotes[name] = layer.quotes[name]
                break
    merged.quotes = quotes
    # the postcode comes from the address, or failing that the district named in the page title
    for source in (merged.address, merged.description):
        postcode, _ = split_postcode(source or "")
        if postcode and source:
            merged.postcode = postcode
            merged.quotes = {**merged.quotes, "postcode": source[:MAX_QUOTE]}
            break
    return merged
