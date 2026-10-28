"""Layer 2 building blocks: turn raw value strings into typed values.

Parsers never guess silently. They return the parsed value plus whether the
reading was ambiguous, or None when the text is not a valid value.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from app.services.extraction.text import repair_numeric_token

# NUMERIC(14,2) upper bound.
MAX_AMOUNT = Decimal("999999999999.99")


@dataclass(frozen=True)
class Parsed[T]:
    value: T
    ambiguous: bool = False
    alternative: str | None = None  # the other reading, for warning messages


# --- Amounts ----------------------------------------------------------------

# A money-looking token: optional sign/parentheses, digits with , . or ' grouping, optional decimals.
AMOUNT_TOKEN = re.compile(
    r"(?<![\w.,])"
    r"\(?-?\s?[$€£₹¥]?\s?"
    # Must start with a real digit; OCR look-alikes (O o l I S) may follow (4.0O, 1O5.00) and are
    # repaired by parse_amount.
    # No space as a group separator here: in table rows "8 212.50" is qty 8 + price 212.50, not 8212.50.
    # Space-grouped amounts ("1 249,50") are accepted only as a whole labelled value (SPACE_GROUPED).
    r"(?:\d{1,3}(?:[,.']\d{3})+|\d[\dOolIS]*)(?:[.,][\dOolIS]{1,2})?"
    r"\)?(?![\w%])",
)


# Integer part: plain digits, groups of three (1,249,500 / 1.249.500), or Indian lakh grouping (1,00,000).
_VALID_GROUPING = re.compile(r"\d+|\d{1,3}(?:[.,]\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}")


def parse_amount(raw: str) -> Parsed[Decimal] | None:
    """Parse a money amount. Handles 1,249.50 / 1.249,50 / 1 249.50 / 1'249.50 / (12.00) / -12.00 / 12,50.

    ``1,234`` and ``1.234`` (exactly three digits after a single separator) are read
    as thousands and flagged ambiguous: they could also be a decimal value.
    """
    text = raw.strip()
    negative = text.startswith("(") and text.endswith(")") or "-" in text
    text = repair_numeric_token(re.sub(r"[()\s$€£₹¥+-]|[A-Z]{3}", "", text).replace("'", ""))
    if not text or not re.fullmatch(r"[\d.,]+", text) or not text[0].isdigit():
        return None

    ambiguous = False
    alternative: str | None = None
    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
    elif dots or commas:
        sep = "." if dots else ","
        head, _, tail = text.rpartition(sep)
        if (dots + commas) > 1:
            # 1.249.500 → thousands; 1.249.50 (OCR read ',' as '.') → last one is the decimal point.
            decimal_sep = sep if len(tail) <= 2 else None
        elif len(tail) == 3:
            # 4,820 is thousands in practice. A lone '.' + 3 digits (1.234) is EU thousands
            # *or* a 3-decimal value: read as thousands, but flag it.
            decimal_sep = None
            if sep == ".":
                ambiguous, alternative = True, f"{head}.{tail}"
        else:
            decimal_sep = sep
    else:
        decimal_sep = None

    int_part, _, frac = text.rpartition(decimal_sep) if decimal_sep else (text, "", "")
    if not _VALID_GROUPING.fullmatch(int_part):  # "1.2.3,4" is not a number, whatever the separators
        return None
    int_part = re.sub(r"[.,]", "", int_part)
    normalized = f"{int_part}.{frac}" if decimal_sep else int_part
    try:
        value = Decimal(normalized)
    except InvalidOperation:
        return None
    if value.as_tuple().exponent < -2 or value > MAX_AMOUNT:  # type: ignore[operator]
        return None
    value = value.quantize(Decimal("0.01"))
    return Parsed(-value if negative and value else value, ambiguous, alternative)


def parse_quantity(raw: str) -> Decimal | None:
    text = repair_numeric_token(raw.strip()).replace(",", ".")
    if not re.fullmatch(r"\d{1,6}(?:\.\d{1,4})?", text):
        return None
    return Decimal(text)


# A value that is *only* one space-grouped amount, optionally with a currency: "EUR 1 249,50".
SPACE_GROUPED = re.compile(r"^[^\d]{0,4}?(\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?)\s*(?:[A-Z]{3}|[$€£₹¥])?$")


def find_amount_spans(text: str) -> list[tuple[int, str, Parsed[Decimal]]]:
    """All parseable amount tokens in a line, left to right, as (start offset, raw, parsed)."""
    # Blank out dates first so "2025-03-18" is not read as the amounts 2025, -03, -18.
    for pattern in DATE_PATTERNS:
        text = pattern.sub(lambda m: " " * len(m.group()), text)
    found = []
    for match in AMOUNT_TOKEN.finditer(text):
        raw = match.group().strip()
        parsed = parse_amount(raw)
        if parsed is not None:
            found.append((match.start() + (len(match.group()) - len(match.group().lstrip())), raw, parsed))
    return found


def find_amounts(text: str) -> list[tuple[str, Parsed[Decimal]]]:
    """All parseable amount tokens in a line, left to right, as (raw, parsed)."""
    return [(raw, parsed) for _, raw, parsed in find_amount_spans(text)]


# --- Dates ------------------------------------------------------------------


class DateOrder(StrEnum):
    DMY = "DMY"
    MDY = "MDY"


_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_MONTH = r"(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")(?![a-z])\.?"
_YEAR = r"(?P<y>\d{4}|\d{2})"

# Ordered: unambiguous forms first.
DATE_PATTERNS = [
    re.compile(r"(?<!\d)(?P<y>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})(?!\d)"),  # 2025-03-18
    re.compile(
        rf"(?<!\d)(?P<d>\d{{1,2}})(?:st|nd|rd|th)?[\s-]*{_MONTH}[\s,-]*{_YEAR}(?!\d)", re.I
    ),  # 18 Mar 2025
    re.compile(
        rf"\b{_MONTH}[\s-]*(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?[\s-]*{_YEAR}(?!\d)", re.I
    ),  # Mar 18, 2025
    re.compile(r"(?<![\d.])(?P<a>\d{1,2})[/.-](?P<b>\d{1,2})[/.-](?P<y>\d{4}|\d{2})(?![\d.])"),  # 18/03/2025
]


def _year(raw: str) -> int:
    year = int(raw)
    return year + 2000 if len(raw) == 2 else year


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_match(match: re.Match[str], order: DateOrder) -> Parsed[date] | None:
    """Turn a DATE_PATTERNS match into a date. None if it is not a real calendar date (e.g. 31/02)."""
    groups = match.groupdict()
    year = _year(groups["y"])
    if groups.get("mon"):
        return (value := _make(year, _MONTHS[groups["mon"].lower()], int(groups["d"]))) and Parsed(value)
    if groups.get("m"):
        return (value := _make(year, int(groups["m"]), int(groups["d"]))) and Parsed(value)

    a, b = int(groups["a"]), int(groups["b"])
    day_first = _make(year, b, a)
    month_first = _make(year, a, b)
    preferred, other = (day_first, month_first) if order == DateOrder.DMY else (month_first, day_first)
    if preferred and other and preferred != other:
        return Parsed(preferred, ambiguous=True, alternative=other.isoformat())
    if preferred or other:
        return Parsed(preferred or other)  # only one reading is a real date (18/03 can only be 18 March)
    return None


_DATE_LIKE = re.compile(r"\b[\dOoIlS]{1,4}(?:[-/.][\dOoIlS]{1,4}){2}\b")


def _repair_date_token(match: re.Match[str]) -> str:
    # "2O25-O3-18": fix look-alikes per part, keeping separators (same length, so spans still align).
    return re.sub(r"[^-/.]+", lambda part: repair_numeric_token(part.group()), match.group())


def find_date(text: str, order: DateOrder) -> tuple[str, Parsed[date] | None] | None:
    """First date-looking token in ``text`` as (raw, parsed). parsed is None for impossible dates."""
    repaired = _DATE_LIKE.sub(_repair_date_token, text)
    best: tuple[int, str, Parsed[date] | None] | None = None
    for pattern in DATE_PATTERNS:
        match = pattern.search(repaired)
        if match and (best is None or match.start() < best[0]):
            # Repair is character-for-character, so the span maps back onto the original text.
            best = (match.start(), text[match.start() : match.end()], parse_date_match(match, order))
    return (best[1], best[2]) if best else None


def parse_date(raw: str, order: DateOrder) -> Parsed[date] | None:
    found = find_date(raw, order)
    return found[1] if found else None


# --- Currency ---------------------------------------------------------------

CURRENCY_CODES = ("USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "CHF", "CNY", "SGD", "NZD", "AED")
_CODE_RE = re.compile(r"\b(" + "|".join(CURRENCY_CODES) + r")\b")
# "$" alone does not say which dollar; it maps to USD with lower confidence (see extractor).
SYMBOLS = {"€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY", "$": "USD"}
_RS_RE = re.compile(r"\bRs\.?\s?\d", re.I)


def find_currencies(text: str) -> list[tuple[str, str]]:
    """All currency mentions as (raw, ISO code), in order of appearance."""
    found: list[tuple[int, str, str]] = [(m.start(), m.group(1), m.group(1)) for m in _CODE_RE.finditer(text)]
    found += [(i, ch, SYMBOLS[ch]) for i, ch in enumerate(text) if ch in SYMBOLS]
    found += [(m.start(), "Rs", "INR") for m in _RS_RE.finditer(text)]
    return [(raw, code) for _, raw, code in sorted(found)]
