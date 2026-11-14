"""Shared types: fetch results, Companies House payloads, module results (plan section 4)."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from app.agents.companies_house.constants import CH_PUBLIC_URL, MAX_LINKUP_QUERIES
from app.contracts import Fact, Finding

T = TypeVar("T")


class Outcome(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    FAILED = "failed"


@dataclass
class Fetch(Generic[T]):  # noqa: UP046 (plan names this Generic[T] dataclass)
    """Result of one external call. A failure is never a NOT_FOUND: only a real 404 is."""

    outcome: Outcome
    value: T | None = None
    error: str | None = None  # "timeout", "429", "500", "network: ...", "401 ..."
    url: str | None = None  # the exact URL fetched, for evidence
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == Outcome.OK


# --- Companies House payloads. Every field is optional: missing means unknown, never a flag. --


def _parse_date(value: Any) -> date | None:
    """Defensive date parse: 'YYYY-MM-DD' (or longer ISO), anything else gives None."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


LooseDate = Annotated[date | None, BeforeValidator(_parse_date)]


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Address(_Loose):
    premises: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    care_of: str | None = None
    po_box: str | None = None

    def one_line(self) -> str:
        parts = [
            self.premises,
            self.address_line_1,
            self.address_line_2,
            self.locality,
            self.region,
            self.postal_code,
        ]
        return ", ".join(p.strip() for p in parts if p and p.strip())


class LastAccounts(_Loose):
    type: str | None = None
    made_up_to: LooseDate = None


class Accounts(_Loose):
    overdue: bool | None = None
    last_accounts: LastAccounts | None = None


class ConfirmationStatement(_Loose):
    overdue: bool | None = None


class CompanyProfile(_Loose):
    company_name: str | None = None
    company_number: str | None = None
    company_status: str | None = None
    company_status_detail: str | None = None
    date_of_creation: LooseDate = None
    type: str | None = None
    has_insolvency_history: bool | None = None
    sic_codes: list[str] = []
    registered_office_address: Address | None = None
    accounts: Accounts | None = None
    confirmation_statement: ConfirmationStatement | None = None

    @field_validator("sic_codes", mode="before")
    @classmethod
    def _sic_list(cls, v: Any) -> list[str]:
        return [str(x) for x in v] if isinstance(v, list) else []

    @property
    def registered_office(self) -> str:
        return self.registered_office_address.one_line() if self.registered_office_address else ""


class SearchHit(_Loose):
    """One `/search/companies` item. CH calls the type `company_type` here (not `type`)."""

    title: str = ""
    company_number: str = ""
    company_status: str | None = None
    company_type: str | None = None
    date_of_creation: LooseDate = None
    address_snippet: str | None = None


class Officer(_Loose):
    name: str = ""
    officer_role: str | None = None
    appointed_on: LooseDate = None
    resigned_on: LooseDate = None
    date_of_birth: Any = None  # CH gives {"month": 4, "year": 1985}; parse with normalise.parse_dob

    @property
    def is_active(self) -> bool:
        return self.resigned_on is None

    @property
    def is_corporate(self) -> bool:
        return bool(self.officer_role and self.officer_role.startswith("corporate-"))


class OfficerList(_Loose):
    """`/company/{n}/officers`. Paginated: `active_count` is the true number of active officers."""

    items: list[Officer] = []
    active_count: int | None = None
    total_results: int | None = None

    @property
    def active(self) -> list[Officer]:
        return [o for o in self.items if o.is_active]

    @property
    def complete(self) -> bool:
        """False when more active officers exist than we fetched (do not claim 'not an officer')."""
        return self.active_count is None or self.active_count <= len(self.active)


class DisqualifiedHit(_Loose):
    title: str = ""
    date_of_birth: Any = None  # str "YYYY-MM-DD" / "YYYY-MM", or a dict; parse defensively
    description: str | None = None


# --- other sources ---------------------------------------------------------------------------


@dataclass
class RogueRecord:
    """One entry on the London Rogue Landlord and Agent Checker."""

    name: str
    number: str | None
    action_type: str | None
    authority: str | None
    action_date: date | None
    expires: date | None
    address: str | None
    offence: str | None
    quote: str  # the entry's company line + enforcement type + date, verbatim


@dataclass
class Snippet:
    """One web search hit headed for the snippet filter."""

    index: int
    title: str
    url: str
    content: str  # the full snippet; quotes are checked against this
    query_key: str = ""  # "scam" | "reviews" | "phone" ...


@dataclass
class FilterContext:
    """What the snippet filter is told about the subject of the snippets."""

    registered_name: str = ""
    company_number: str = ""
    registered_office: str = ""
    supplied_name: str = ""
    subject: Literal["company", "phone"] = "company"
    phone: str | None = None  # set when subject == "phone"


@dataclass
class KeptSnippet:
    snippet: Snippet
    label: Literal["scam_report", "negative_review"]
    quote: str  # verbatim substring of snippet.content, <= 200 chars
    via_llm: bool  # False when the keyword fallback kept it


# --- module plumbing -------------------------------------------------------------------------


@dataclass
class ResolvedCompany:
    """A company the register module pinned down. Reputation and contact start from this."""

    profile: CompanyProfile
    number: str  # normalised
    matched_by: Literal["number", "name"]
    supplied_name: str | None = None  # the name the student was given

    @property
    def registered_name(self) -> str:
        return self.profile.company_name or self.supplied_name or ""

    @property
    def registered_office(self) -> str:
        return self.profile.registered_office

    @property
    def public_url(self) -> str:
        return CH_PUBLIC_URL.format(number=self.number)


@dataclass
class QueryBudget:
    """Counts Linkup queries so one run never exceeds the cap (App. I.12)."""

    limit: int = MAX_LINKUP_QUERIES
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


@dataclass
class ModuleResult:
    name: str  # "register" | "reputation" | "contact" | "property"
    findings: list[Finding] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)  # e.g. "scam reports (Linkup: timeout)"
    questions: list[str] = field(default_factory=list)
    fatal: bool = False  # True only for register when the company could not be fetched
    error: str | None = None  # set with fatal


@dataclass
class RegisterResult(ModuleResult):
    resolved_company: ResolvedCompany | None = None
