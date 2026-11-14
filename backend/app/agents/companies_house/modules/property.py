"""Property module: does the listing's postcode exist, and is it in the area the listing names?

Plan section 8. Never a hard flag, never a fact. A lookup failure is a failed check, never
'invalid': only a real 404 from postcodes.io counts as 'postcode not found'.
"""

import asyncio
import json
import re
from typing import Any

from app.agents.companies_house.constants import (
    CONF,
    EV_POSTCODES,
    POSTCODES_TIMEOUT_S,
    POSTCODES_URL,
)
from app.agents.companies_house.evidence import make_finding, student_refs
from app.agents.companies_house.models import ModuleResult, Outcome
from app.agents.companies_house.normalise import extract_postcode
from app.agents.companies_house.retry import Sleep
from app.agents.companies_house.web import http_get
from app.contracts import Case, Category, EvidenceRef, Finding, Severity
from app.core.agent import AgentContext

LONDON_AREAS: tuple[str, ...] = (
    "Barking and Dagenham",
    "Barnet",
    "Bexley",
    "Brent",
    "Bromley",
    "Camden",
    "City of London",
    "Croydon",
    "Ealing",
    "Enfield",
    "Greenwich",
    "Hackney",
    "Hammersmith and Fulham",
    "Haringey",
    "Harrow",
    "Havering",
    "Hillingdon",
    "Hounslow",
    "Islington",
    "Kensington and Chelsea",
    "Kingston upon Thames",
    "Lambeth",
    "Lewisham",
    "Merton",
    "Newham",
    "Redbridge",
    "Richmond upon Thames",
    "Southwark",
    "Sutton",
    "Tower Hamlets",
    "Waltham Forest",
    "Wandsworth",
    "Westminster",
)

# A borough name followed by one of these is a street/place name ("Harrow Road"), not an area.
_STREET_WORDS = (
    "road|rd|street|st|lane|ln|avenue|ave|close|court|way|gardens|gdns|grove|place|square|"
    "terrace|crescent|drive|hill|park|green|walk|row|mews|rise|gate"
)
_PREFIX_RE = re.compile(r"^(london borough of|royal borough of|city of westminster)\s*", re.I)
_NOT_FOUND_LEAD = (
    "This postcode wasn't found in the national postcode list. "
    "Very new addresses can be missing, so double-check it."
)


def _canon(name: str) -> str:
    """Lower-case area name with 'London Borough of' style prefixes removed."""
    text = name.strip().lower()
    if text.startswith("city of westminster"):
        return "westminster"
    return _PREFIX_RE.sub("", text).strip()


def claimed_areas(text: str) -> list[str]:
    """London areas explicitly named in `text` (whole word, any case, not as a street name)."""
    found: list[str] = []
    for area in LONDON_AREAS:
        pattern = rf"\b{re.escape(area)}\b(?!\s+(?:{_STREET_WORDS})\b)"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(area)
    return found


def area_mismatch(listing_text: str, admin_district: str | None) -> str | None:
    """The area the listing claims when it names London areas and none matches `admin_district`.

    None when there is no district, no area named, or any named area equals the district.
    """
    if not admin_district or not admin_district.strip():
        return None
    claimed = claimed_areas(listing_text)
    if not claimed:
        return None
    district = _canon(admin_district)
    if any(_canon(area) == district for area in claimed):
        return None
    return claimed[0]


def _listing_text(case: Case) -> str:
    listing = case.listing
    if listing is None:
        return ""
    return "\n".join(p for p in (listing.address, listing.description) if p)


def _written_postcode(case: Case) -> str | None:
    """The postcode as the listing wrote it (field, else the address match), for quoting."""
    listing = case.listing
    if listing is None:
        return None
    if listing.postcode and listing.postcode.strip():
        return listing.postcode.strip()
    return None


def _district(body: Any) -> tuple[bool, str | None]:
    """(well-formed?, admin_district) from a postcodes.io 200 body."""
    if not isinstance(body, dict):
        return False, None
    result = body.get("result")
    if not isinstance(result, dict):
        return False, None
    district = result.get("admin_district")
    if district is None:
        return True, None
    if isinstance(district, str):
        return True, district
    return False, None


async def run(
    ctx: AgentContext,
    case: Case,
    *,
    sleep: Sleep = asyncio.sleep,
) -> ModuleResult:
    """Check that the listing's postcode exists and sits in the area the listing names."""
    result = ModuleResult(name="property")
    postcode = extract_postcode(case.listing)
    if postcode is None:
        return result

    url = POSTCODES_URL.format(postcode=postcode.replace(" ", ""))
    fetch = await http_get(ctx, url, per_try_timeout=POSTCODES_TIMEOUT_S, sleep=sleep)
    source = fetch.url or url

    if fetch.outcome == Outcome.FAILED:
        result.failed_checks.append(f"postcode lookup (postcodes.io: {fetch.error})")
        return result

    try:
        finding: Finding | None
        if fetch.outcome == Outcome.NOT_FOUND:
            written = _written_postcode(case)
            needles = [n for n in (written, postcode) if n]
            refs = [
                EvidenceRef(evidence_id=EV_POSTCODES, quote=f"postcode: {postcode} (not found)")
            ]
            refs += student_refs(case, needles)
            finding = make_finding(
                "postcode-invalid",
                title="The listing's postcode wasn't found",
                detail=f"{_NOT_FOUND_LEAD} Postcode checked: {postcode}.",
                severity=Severity.MEDIUM,
                confidence=CONF["postcode-invalid"],
                evidence=refs,
                sources=[source],
                category=Category.PROPERTY,
            )
        else:
            assert fetch.value is not None
            try:
                body = fetch.value.json()
            except (json.JSONDecodeError, ValueError):
                body = None
            well_formed, district = _district(body)
            if not well_formed:
                result.failed_checks.append("postcode lookup (postcodes.io: malformed response)")
                return result
            claimed = area_mismatch(_listing_text(case), district)
            if claimed is None or district is None:
                return result
            refs = [EvidenceRef(evidence_id=EV_POSTCODES, quote=f"admin_district: {district}")]
            refs += student_refs(case, [claimed])
            finding = make_finding(
                "postcode-area-mismatch",
                title="The postcode is in a different area from the listing",
                detail=f"{postcode} is in {district}, not {claimed} as the listing says.",
                severity=Severity.LOW,
                confidence=CONF["postcode-area-mismatch"],
                evidence=refs,
                sources=[source],
                category=Category.PROPERTY,
            )
        result.findings.append(finding)
    except Exception as exc:  # never raise out of a module
        ctx.log.warning("companies_house: property module failed: %s", exc)
        result.failed_checks.append(f"postcode lookup ({type(exc).__name__})")
    return result
