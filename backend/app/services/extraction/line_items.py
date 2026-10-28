"""Layer 3: line-item extraction from table-like text.

With a header row ("Description  Qty  Price  Amount") items are read from the
lines below it until the summary block (Subtotal/Tax/Total). Without a header,
only lines whose numbers are self-consistent (qty × unit ≈ total) are accepted, so
addresses, phone numbers and dates are not mistaken for items.
"""

import re
from decimal import Decimal

from app.services import confidence
from app.services.extraction.parsers import DATE_PATTERNS, find_amount_spans, find_amounts, parse_quantity
from app.services.extraction.text import Line
from app.services.extraction.text import fuzzy_label as fz
from app.services.extraction.types import LineItemResult

_HEADER_WORDS = re.compile(
    r"\b(description|item|items|product|service|details|particulars|qty|quantity|units?|hrs|hours|"
    r"price|rate|unit\s*price|amount|total|line\s*total)\b",
    re.I,
)
_SUMMARY = re.compile(
    "|".join(
        [
            fz("subtotal"),
            fz("sub", "total"),
            fz("total"),
            r"\b(?:tax|vat|gst|hst|cgst|sgst|igst)\b",
            r"\bdiscount\b",
            r"\bamount\s+(?:due|paid)\b",
            r"\bbalance\b",
            r"\bshipping\b(?!\s+(?:address|to))",
            r"\bchange\b",
            r"\btip\b",
        ]
    ),
    re.I,
)


def is_table_header(line: Line) -> bool:
    return len({m.group(1).lower() for m in _HEADER_WORDS.finditer(line.text)}) >= 2 and not find_amounts(
        line.text
    )


def _has_date(text: str) -> bool:
    return any(p.search(text) for p in DATE_PATTERNS)


def _parse_item(line: Line) -> tuple[str, Decimal | None, Decimal | None, Decimal | None] | None:
    """(description, quantity, unit_price, total) from one line, or None if it isn't an item line."""
    text = line.text
    spans = find_amount_spans(text)
    if not spans:
        return None
    # The numeric columns are the trailing numbers; anything earlier belongs to the description
    # ("Model 2000 printer  1  199.00  199.00").
    columns = spans[-3:]
    description = text[: columns[0][0]].strip(" -:|x×@\t")
    if sum(ch.isalpha() for ch in description) < 2:
        return None

    raws = [raw for _, raw, _ in columns]
    values = [parsed.value for _, _, parsed in columns]
    if len(values) == 3:  # "Widget 4 x 12.50 50.00" / "Widget 4 12.50 50.00"
        return description, parse_quantity(raws[0]), values[1], values[2]
    if len(values) == 2:
        if re.fullmatch(r"\d{1,4}", raws[0]):  # "Widget 4 50.00" → qty, total
            return description, Decimal(raws[0]), None, values[1]
        return description, None, values[0], values[1]  # "Widget 12.50 50.00" → unit, total
    return description, None, None, values[0]


def _consistent(qty: Decimal | None, unit: Decimal | None, total: Decimal | None) -> bool | None:
    if qty is None or unit is None or total is None:
        return None
    return abs(qty * unit - total) <= Decimal("0.02")


def extract_line_items(lines: list[Line]) -> list[LineItemResult]:
    header_at = next((i for i, line in enumerate(lines) if is_table_header(line)), None)
    items: list[LineItemResult] = []

    if header_at is not None:
        for line in lines[header_at + 1 :]:
            if _SUMMARY.search(line.text):
                break
            if is_table_header(line):  # table header repeated on the next page
                continue
            parsed = _parse_item(line) if not _has_date(line.text) else None
            if parsed is None:
                # A line without numbers continues the previous description (wrapped text).
                if items and not find_amounts(line.text) and len(line.text) < 80:
                    items[-1].description = f"{items[-1].description} {line.text}".strip()
                continue
            items.append(_make_item(parsed, line, in_table=True))
        return items

    for line in lines:  # no header: only accept lines that prove themselves arithmetically
        if _SUMMARY.search(line.text) or _has_date(line.text):
            continue
        parsed = _parse_item(line)
        if parsed and _consistent(parsed[1], parsed[2], parsed[3]):
            items.append(_make_item(parsed, line, in_table=False))
    return items


def _make_item(parsed, line: Line, *, in_table: bool) -> LineItemResult:
    description, qty, unit, total = parsed
    return LineItemResult(
        description=description[:500],
        quantity=qty,
        unit_price=unit,
        total=total,
        confidence=confidence.line_item_confidence(
            in_table=in_table, arithmetic_ok=_consistent(qty, unit, total), ocr_confidence=line.ocr_confidence
        ),
        page_number=line.page_number,
        raw=line.text,
    )
