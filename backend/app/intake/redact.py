"""Mask financial identifiers in uploaded text before anything is stored or sent to an LLM.

Intake masks once, so the case record, the LLM providers, the logs and the UI never see a full bank
account, sort code, IBAN or card number. Quotes stay exact substrings of the stored (masked) text,
so agents can keep checking quotes word for word (golden rule 6).

Masked forms, which agents can recognise:

| Input | Masked |
| --- | --- |
| IBAN `DE89 3704 0044 0532 0130 00` | `DE** **** **** 3000` (country code kept: it is a signal) |
| Sort code `12-34-56`, `12 34 56`, `sort code 123456` | `**-**-56` |
| Card `4111 1111 1111 1111` | `**** **** **** 1111` |
| Any other run of 6+ digits (accounts, phones) | `****1234` |

Company registration numbers are public and needed for the Companies House check, so a number right
after "company number", "registration number", "CRN" or "Companies House" is left as it is.
"""

import re

_I = re.IGNORECASE

_IBAN = re.compile(r"\b([A-Z]{2})\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_CARD = re.compile(r"(?<![\d*])(?:\d{4}[ -]){3}(\d{4})(?![\d*])")
_SORT_CODE = re.compile(r"(?<![\d*-])\d{2}([- ])\d{2}\1(\d{2})(?![\d*-])")
_SORT_CODE_RUN = re.compile(r"(\bsort ?code:? ?)\d{4}(\d{2})\b", _I)
# not glued to letters, so "SC123456" (a Scottish company number) is left alone
_LONG_NUMBER = re.compile(r"(?<![\dA-Za-z*])\d{6,}(?![\dA-Za-z*])")
_COMPANY_CONTEXT = re.compile(
    r"(?:company|registration|registered|reg\.?)(?: number| no\.?| num\.?)?:?\s*$|"
    r"\bcrn:?\s*$|companies house\b.{0,20}$",
    _I,
)
_CONTEXT_CHARS = 40


def _mask_iban(match: re.Match[str]) -> str:
    digits = re.sub(r"\s", "", match.group(0))
    return f"{match.group(1)}** **** **** {digits[-4:]}"


def _mask_long(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        before = text[max(0, match.start() - _CONTEXT_CHARS) : match.start()]
        if _COMPANY_CONTEXT.search(before):
            return match.group(0)
        return f"****{match.group(0)[-4:]}"

    return _LONG_NUMBER.sub(repl, text)


def mask_sensitive(text: str) -> str:
    """`text` with IBANs, card numbers, sort codes and account-like numbers masked."""
    text = _IBAN.sub(_mask_iban, text)
    text = _CARD.sub(lambda m: f"**** **** **** {m.group(1)}", text)
    text = _SORT_CODE_RUN.sub(lambda m: f"{m.group(1)}**-**-{m.group(2)}", text)
    text = _SORT_CODE.sub(lambda m: f"**-**-{m.group(2)}", text)
    return _mask_long(text)
