"""Thresholds, status sets, domain lists, query templates and confidences (plan 5.3, App. D)."""

from typing import Final

AGENT_NAME: Final = "companies_house"

# --- endpoints -------------------------------------------------------------------------------
CH_BASE_URL: Final = "https://api.company-information.service.gov.uk"
CH_PUBLIC_URL: Final = "https://find-and-update.company-information.service.gov.uk/company/{number}"
POSTCODES_URL: Final = "https://api.postcodes.io/postcodes/{postcode}"
RDAP_URL: Final = "https://rdap.org/domain/{domain}"
ROGUE_CHECKER_URL: Final = (
    "https://www.london.gov.uk/programmes-strategies/housing-and-land/renting-home/"
    "private-renting/check-landlord-or-agent/rogue-landlord-and-agent-checker"
)
ROGUE_USER_AGENT: Final = "Warden/0.1 (Imperial AI Hackathon student project)"
ROGUE_PAGE_SIZE: Final = 10
ROGUE_MAX_REQUESTS: Final = 2
ROGUE_NO_RESULTS_TEXT: Final = "Sorry, no results were found"

# --- retry and timeouts (seconds) -----------------------------------------------------------
RETRY_ATTEMPTS: Final = 3
RETRY_BACKOFF: Final = (1.0, 3.0, 9.0)
RETRY_AFTER_CAP_S: Final = 10.0
CH_TIMEOUT_S: Final = 10.0
POSTCODES_TIMEOUT_S: Final = 8.0
RDAP_TIMEOUT_S: Final = 8.0
ROGUE_TIMEOUT_S: Final = 15.0
LINKUP_STANDARD_TIMEOUT_S: Final = 15.0
LINKUP_DEEP_TIMEOUT_S: Final = 35.0
AGENT_TIMEOUT_S: Final = 120.0
MAX_LINKUP_QUERIES: Final = 8

# --- register rules -------------------------------------------------------------------------
# NOTE: voluntary-arrangement is deliberately NOT dead (a company in a CVA still trades).
DEAD_STATUSES: Final = frozenset(
    {
        "dissolved",
        "liquidation",
        "receivership",
        "administration",
        "insolvency-proceedings",
        "converted-closed",
        "removed",
        "closed",
    }
)
# company_status_detail values that mean "about to disappear": suspicious, never a clear.
STRIKE_OFF_DETAILS: Final = frozenset(
    {"active-proposal-to-strike-off", "petition-to-restore-dissolved"}
)
YOUNG_MONTHS: Final = 12
ESTABLISHED_MONTHS: Final = 24
NAME_MATCH_MIN: Final = 90
NAME_MATCH_GAP: Final = 5
NAME_NUMBER_MISMATCH_MAX: Final = 80  # number resolves to a name scoring below this vs the supplied
MAX_DISQUALIFIED_LOOKUPS: Final = 3
OFFICERS_PAGE_SIZE: Final = 100
SEARCH_PAGE_SIZE: Final = 20
# 68310 agencies, 68320 management, 68100 buying/selling own property, 68209 other letting.
PROPERTY_SIC: Final = frozenset({"68310", "68320", "68100", "68209"})
VIRTUAL_OFFICE_MARKERS: Final = (
    "71-75 shelton street",
    "20-22 wenlock road",
    "kemp house",
    "152-160 city road",
    "128 city road",
    "27 old gloucester street",
    "86-90 paul street",
    "85 great portland street",
    "167-169 great portland street",
)
NAME_SUFFIXES: Final = frozenset({"limited", "ltd", "llp", "plc", "lp", "uk", "company", "co"})
PERSON_TITLES: Final = frozenset({"mr", "mrs", "ms", "miss", "dr"})

# --- reputation -----------------------------------------------------------------------------
MAX_SNIPPETS_TO_FILTER: Final = 20
SNIPPET_PROMPT_CHARS: Final = 600
MAX_QUOTE_CHARS: Final = 200
MAX_FINDINGS_PER_KIND: Final = 3
QUERY_SCAM: Final = '"{name}" letting agent scam OR fraud OR deposit London'
QUERY_REVIEWS: Final = '"{name}" reviews Google Trustpilot allAgents'
QUERY_REDRESS: Final = '"{name}" Property Redress Scheme OR "The Property Ombudsman" member'
QUERY_CMP: Final = '"{name}" client money protection Propertymark OR safeagent'
QUERY_ROGUE_FALLBACK: Final = '"{name}" site:london.gov.uk rogue landlords checker'
QUERY_PHONE: Final = '"{phone}" scam'
REDRESS_DOMAINS: Final = frozenset({"theprs.co.uk", "tpos.co.uk"})
CMP_DOMAINS: Final = frozenset({"propertymark.co.uk", "safeagent.co.uk", "ukala.org.uk"})
FALLBACK_KEYWORDS: Final = (
    "scam",
    "fraud",
    "fake",
    "deposit",
    "stole",
    "never returned",
    "no viewing",
    "wire",
    "bank transfer",
)
ROGUE_NAME_MATCH_MIN: Final = 95

# --- contact --------------------------------------------------------------------------------
WEBMAIL_DOMAINS: Final = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
    }
)
WEBMAIL_PREFIXES: Final = ("hotmail.", "live.", "yahoo.")  # hotmail.co.uk, yahoo.com ...
BRAND_DOMAINS: Final = {
    "rightmove": {"rightmove.co.uk"},
    "zoopla": {"zoopla.co.uk"},
    "onthemarket": {"onthemarket.com"},
    "spareroom": {"spareroom.co.uk"},
    "openrent": {"openrent.com", "openrent.co.uk"},
    "unitestudents": {"unitestudents.com"},
    "iqstudent": {"iqstudentaccommodation.com"},
    "foxtons": {"foxtons.co.uk"},
}
NEW_DOMAIN_DAYS: Final = 90

# --- evidence ids (App. C) ------------------------------------------------------------------
EV_REGISTER: Final = "companies_house"
EV_WEB: Final = "web"
EV_ROGUE: Final = "london_rogue_checker"
EV_POSTCODES: Final = "postcodes_io"
EV_RDAP: Final = "rdap"
EXTERNAL_EVIDENCE_IDS: Final = frozenset({EV_REGISTER, EV_WEB, EV_ROGUE, EV_POSTCODES, EV_RDAP})

# --- confidences (App. D, deliberate: they decide whether a check flips) ---------------------
CONF: Final = {
    "not-found": 0.95,
    "dissolved": 0.95,
    "name-number-mismatch": 0.9,
    "name-no-match": 0.7,
    "ambiguous-match": 0.5,
    "young-company": 0.7,
    "officer-mismatch": 0.5,  # medium but must NOT flip the check
    "disqualified-director": 0.85,
    "dormant": 0.7,
    "insolvency-history": 0.7,
    "strike-off-proposed": 0.7,
    "overdue-filings": 0.5,
    "non-property-sic": 0.5,
    "virtual-office": 0.5,
    "webmail": 0.5,
    "scam-report": 0.75,
    "scam-report-fallback": 0.6,
    "negative-review": 0.6,
    "rogue-checker": 0.9,
    "rogue-checker-name": 0.6,
    "lookalike-domain": 0.8,
    "new-domain": 0.7,
    "phone-scam": 0.7,
    "postcode-invalid": 0.8,
    "postcode-area-mismatch": 0.5,
    "registered-active": 0.6,  # a real company does not prove the messenger works for it
    "redress-member": 0.5,
    "cmp-member": 0.5,
    "not-run": 0.0,
}
