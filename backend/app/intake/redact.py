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
| Any other run of 6+ digits (account numbers) | `****1234` |

Only financial data is masked. Left as they are, because the Companies House contact check needs
them in full:

- phone numbers (`07700 900123`, `+44 7700 900123`, `020 7946 0958`) and email addresses;
- company registration numbers: a number right after "company number", "registration number",
  "CRN" or "Companies House", and any bare 8-digit number with no bank wording near it. A UK
  account number is also 8 digits, so an 8-digit number is masked when "account", "sort code",
  "bank", "IBAN", "payee" or "transfer" (or a sort code) is close by.
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
# UK national (01, 02, 03, 07, 08 + 8 or 9 more digits) and international (+44..., 0044...)
# numbers, with spaces, hyphens or "(0)" inside. Matched first, so no rule masks part of one.
_PHONE = re.compile(
    r"(?<![\w*+])(?:(?:\+|00)[1-9]\d{0,2}[ -]?(?:\(0\)[ -]?)?\d(?:[ -]?\d){7,11}"
    r"|\(?0[12378]\d{0,3}\)?(?:[ -]?\d){6,9})(?![\d*])"
)
_COMPANY_NUMBER_DIGITS = 8  # also the length of a UK bank account number
_BANK_CONTEXT = re.compile(
    r"\b(?:account|acc(?:t|ount)?\b|a/c|sort ?code|bank|iban|payee|transfer)|\*\*-\*\*-", _I
)
_BANK_BEFORE_CHARS = 60
_BANK_AFTER_CHARS = 30


def _mask_iban(match: re.Match[str]) -> str:
    digits = re.sub(r"\s", "", match.group(0))
    return f"{match.group(1)}** **** **** {digits[-4:]}"


def _near_bank_words(text: str, start: int, end: int) -> bool:
    nearby = text[max(0, start - _BANK_BEFORE_CHARS) : start] + " " + text[end:][:_BANK_AFTER_CHARS]
    return _BANK_CONTEXT.search(nearby) is not None


def _mask_long(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        before = text[max(0, match.start() - _CONTEXT_CHARS) : match.start()]
        if _COMPANY_CONTEXT.search(before):
            return match.group(0)
        bare_company_number = len(match.group(0)) == _COMPANY_NUMBER_DIGITS
        if bare_company_number and not _near_bank_words(text, match.start(), match.end()):
            return match.group(0)
        return f"****{match.group(0)[-4:]}"

    return _LONG_NUMBER.sub(repl, text)


def _mask_accounts(text: str) -> str:
    text = _SORT_CODE_RUN.sub(lambda m: f"{m.group(1)}**-**-{m.group(2)}", text)
    text = _SORT_CODE.sub(lambda m: f"**-**-{m.group(2)}", text)
    return _mask_long(text)


def mask_sensitive(text: str) -> str:
    """`text` with IBANs, card numbers, sort codes and account numbers masked.

    IBANs and cards go first (an IBAN can contain "0044 ..."). Then phone numbers are cut out
    and put back untouched, so the sort-code and long-number rules cannot mask part of one.
    """
    text = _IBAN.sub(_mask_iban, text)
    text = _CARD.sub(lambda m: f"**** **** **** {m.group(1)}", text)
    parts: list[str] = []
    last = 0
    for phone in _PHONE.finditer(text):
        parts += [_mask_accounts(text[last : phone.start()]), phone.group(0)]
        last = phone.end()
    parts.append(_mask_accounts(text[last:]))
    return "".join(parts)
