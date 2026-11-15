"""Pure helpers: numbers, names, postcodes, contacts, dates (plan App. A, E)."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from app.agents.companies_house.constants import NAME_SUFFIXES, PERSON_TITLES
from app.contracts import Case, Listing

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.IGNORECASE)
FULL_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\w+])(?:\+44|0)[\d\s()-]{8,14}\d(?!\d)")
MAX_EMAILS = 2
MAX_PHONES = 1


# --- company numbers and names ---------------------------------------------------------------


def normalise_number(raw: str) -> str:
    """Strip spaces, uppercase, zero-pad all-digit numbers to 8 (same as crosscheck)."""
    n = re.sub(r"\s", "", raw).upper()
    return n.zfill(8) if n.isdigit() else n


def normalise_name(raw: str) -> str:
    """Lowercase, no punctuation, '&' as 'and', no company suffixes, no leading 'the'."""
    words = re.sub(r"[^\w\s&]", " ", raw.lower()).replace("&", " and ").split()
    words = [w for w in words if w not in NAME_SUFFIXES]
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def name_score(a: str, b: str) -> int:
    """0..100 similarity of two names after normalising. difflib (rapidfuzz isn't installed)."""
    na, nb = normalise_name(a), normalise_name(b)
    if not na and not nb:
        return 0
    return round(SequenceMatcher(None, na, nb).ratio() * 100)


_BRANCH_PAREN_RE = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")
_BRANCH_SEP_RE = re.compile(r"\s*,\s*|\s+[-\u2013\u2014]\s+|\s*\|\s*")
_BRANCH_MIN_BASE = 3


def strip_branch_suffix(name: str) -> str | None:
    """The agency's base name when `name` ends in a branch ("Chestertons, Camden & Primrose Hill",
    "Foxtons - Camden", "Hawes and Co (Wimbledon)", "Dexters | Kentish Town"), else None.

    Listings name the agency with its branch, but the register only knows the company. The caller
    must try the full name first: some real names contain a comma ("Smith, Jones & Co Ltd").
    """
    base = _BRANCH_SEP_RE.split(name.strip(), maxsplit=1)[0]
    base = _BRANCH_PAREN_RE.sub("", base).strip()
    if base == name.strip() or len(normalise_name(base)) < _BRANCH_MIN_BASE:
        return None
    return base


def slug(text: str) -> str:
    """Lowercase [a-z0-9]+ words joined by '-', at most 40 chars."""
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:40].strip("-")


def url_hash8(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:8]


def domain_of(email_or_url: str) -> str:
    """Lowercase host of an email address or URL, without a leading 'www.'."""
    value = email_or_url.strip()
    if "@" in value and "//" not in value:
        host = value.rsplit("@", 1)[1]
    else:
        parsed = urlparse(value if "//" in value else f"//{value}")
        host = parsed.hostname or ""
    host = host.lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def host_matches(host: str, domains: frozenset[str] | set[str]) -> bool:
    """True when `host` is one of `domains` or a subdomain of one."""
    return any(host == d or host.endswith("." + d) for d in domains)


# --- people ----------------------------------------------------------------------------------


def strip_title(name: str) -> str:
    """Drop a leading Mr/Mrs/Ms/Miss/Dr from a person's name."""
    words = name.split()
    while words and words[0].lower().rstrip(".") in PERSON_TITLES:
        words = words[1:]
    return " ".join(words)


def split_officer_name(name: str) -> tuple[str, list[str]]:
    """(surname, forenames) from 'SURNAME, Forenames' or, with no comma, 'Forenames Surname'."""
    if "," in name:
        surname, _, rest = name.partition(",")
        return surname.strip().lower(), rest.lower().split()
    words = name.lower().split()
    if not words:
        return "", []
    return words[-1], words[:-1]


def person_matches_officer(person: str, officer_name: str) -> bool:
    """True when the surname matches and the first forename (or its initial) matches.

    Handles CH's 'SURNAME, Forenames' and names without a comma. Titles are stripped.
    """
    p_surname, p_forenames = split_officer_name(strip_title(person))
    o_surname, o_forenames = split_officer_name(strip_title(officer_name))
    if not p_surname or p_surname != o_surname:
        return False
    if not p_forenames or not o_forenames:
        return True  # surname-only on one side: surname match is all we can say
    p_first, o_first = p_forenames[0].rstrip("."), o_forenames[0]
    # Same forename, an initial ('H'), or a short form ('Sam' / 'Samuel') all count.
    return o_first.startswith(p_first) or p_first.startswith(o_first)


def parse_dob(value: Any) -> tuple[int, int | None] | None:
    """(year, month|None) from 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY' or {'year','month'}. Defensive."""
    year: Any = None
    month: Any = None
    if isinstance(value, dict):
        year, month = value.get("year"), value.get("month")
    elif isinstance(value, str):
        parts = value.strip().split("-")
        year = parts[0] if parts else None
        month = parts[1] if len(parts) > 1 else None
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    if not 1850 <= y <= 2100:
        return None
    try:
        m = int(month) if month is not None else None
    except (TypeError, ValueError):
        m = None
    return (y, m if m is not None and 1 <= m <= 12 else None)


# --- dates -----------------------------------------------------------------------------------


def months_between(created: date, today: date) -> int:
    """Whole months from `created` to `today` (no dateutil)."""
    return (
        (today.year - created.year) * 12
        + (today.month - created.month)
        - (1 if today.day < created.day else 0)
    )


# --- postcodes and contacts ------------------------------------------------------------------


def normalise_postcode(raw: str) -> str:
    """Uppercase with a single space before the last 3 characters."""
    compact = re.sub(r"\s", "", raw).upper()
    return f"{compact[:-3]} {compact[-3:]}" if len(compact) > 3 else compact


def extract_postcode(listing: Listing | None) -> str | None:
    """The listing's postcode (normalised), else one found in its address, else None."""
    if listing is None:
        return None
    if listing.postcode and FULL_POSTCODE_RE.match(listing.postcode.strip()):
        return normalise_postcode(listing.postcode)
    # An outward-only code ("W12") or free text is not a postcode we can look up: never let it
    # reach postcodes.io, which would 404 and look like a fake address.
    if listing.address:
        match = POSTCODE_RE.search(listing.address)
        if match:
            return normalise_postcode(match.group(1) + match.group(2))
    return None


@dataclass
class Contacts:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)  # digits only, UK national form (07...)

    def keys(self) -> list[str]:
        """Sorted stable keys for the input hash."""
        return sorted([f"email:{e}" for e in self.emails] + [f"phone:{p}" for p in self.phones])


def normalise_phone(raw: str) -> str | None:
    """UK national digits ('07911123456') for 07... and 020... numbers, else None."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+44") and digits.startswith("44"):
        digits = "0" + digits[2:]
    if len(digits) == 11 and (digits.startswith("07") or digits.startswith("020")):
        return digits
    return None


def extract_contacts(case: Case) -> Contacts:
    """Landlord email/phone if set; only if both are empty, scan the AGENT's messages.

    Student messages are never scanned, so the student's own contact details are ignored.
    """
    ll = case.landlord
    emails: list[str] = []
    phones: list[str] = []
    if ll and ll.email and ll.email.strip():
        emails.append(ll.email.strip().lower())
    if ll and ll.phone and ll.phone.strip():
        phone = normalise_phone(ll.phone)
        if phone:
            phones.append(phone)
    if emails or phones:
        return Contacts(emails[:MAX_EMAILS], phones[:MAX_PHONES])
    for message in case.messages:
        if message.sender != "agent":
            continue
        for found in EMAIL_RE.findall(message.text):
            e = found.lower().rstrip(".")
            if e not in emails:
                emails.append(e)
        for found in _PHONE_CANDIDATE_RE.findall(message.text):
            p = normalise_phone(found)
            if p and p not in phones:
                phones.append(p)
    return Contacts(emails[:MAX_EMAILS], phones[:MAX_PHONES])
