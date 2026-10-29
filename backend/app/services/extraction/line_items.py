"""Layer 3: line-item extraction from table-like text.

With a header row ("Description  Qty  Unit Price  VAT  Amount") the header names the
numeric columns, so a row with that many numbers is mapped column by column: a separate
tax column is never mistaken for the unit price. Rows are read until the summary block
(Subtotal/Tax/Total). A line with fewer numbers than columns and no column gap continues
the previous description ("(April to June 2025, 25 seats)").

Without a header, a line is accepted only when it proves itself:
- arithmetic: qty × unit ≈ total ("Widget 4 x 12.50 50.00", "2 x Oat milk @ 2.10 4.20"); or
- the sum check: all priced lines above the first total line add up exactly to the
  subtotal/total found on the document (till receipts: "Sourdough loaf 3.80").
Otherwise no row is produced: addresses, phone numbers and dates never become items.
"""

import re
from collections.abc import Sequence
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
# Numeric column names in a header, longest alternatives first ("Unit Price" is one column).
_COLUMN_WORDS = re.compile(
    r"\b(unit\s*price|unit\s*cost|net\s*amount|line\s*total|qty|quantity|units?|hrs|hours|price|rate|"
    r"vat|gst|tax|disc(?:ount)?|amount|total)\b",
    re.I,
)
_COLUMN_KIND = {
    "qty": "qty", "quantity": "qty", "unit": "qty", "units": "qty", "hrs": "qty", "hours": "qty",
    "price": "unit", "rate": "unit", "unitprice": "unit", "unitcost": "unit",
    "vat": "tax", "gst": "tax", "tax": "tax", "disc": "discount", "discount": "discount",
    "amount": "total", "total": "total", "netamount": "total", "linetotal": "total",
}  # fmt: skip
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
_TOTAL_LINE = re.compile(fz("subtotal") + "|" + fz("sub", "total") + "|" + fz("total"), re.I)
_COLUMN_GAP = re.compile(r"\S\s{2,}\S")
# "2 x Oat milk 1L @ 2.10  4.20" · "Bananas 1.24 kg @ 1.10/kg  1.36"
_AT_LINE = re.compile(
    r"^(?:(?P<lead_qty>\d+(?:[.,]\d+)?)\s*[x×]\s+)?(?P<desc>.+?)"
    r"(?P<trail>\s+(?P<trail_qty>\d+(?:[.,]\d+)?)\s*(?:kg|g|lb|lbs|l|ml|pcs?|ea)\b)?"
    r"\s*@\s*(?P<unit>\d[\d.,]*)(?:\s*/\s*[a-z]+)?\s+(?P<total>-?\d[\d.,]*)\s*$",
    re.I,
)
# "Widget assembly kit 4x" / "Widget 4 x": a quantity glued to the end of the description.
_TRAILING_QTY = re.compile(r"^(?P<desc>.*?\D)\s*(?P<qty>\d{1,4})\s*[x×]$", re.I)


def is_table_header(line: Line) -> bool:
    return len({m.group(1).lower() for m in _HEADER_WORDS.finditer(line.text)}) >= 2 and not find_amounts(
        line.text
    )


def header_columns(line: Line) -> list[str]:
    """Kinds of the numeric columns named by a header row, left to right."""
    kinds = []
    for match in _COLUMN_WORDS.finditer(line.text):
        kinds.append(_COLUMN_KIND[re.sub(r"\s+", "", match.group(1).lower())])
    return kinds


def _has_date(text: str) -> bool:
    return any(p.search(text) for p in DATE_PATTERNS)


Parsed = tuple[str, Decimal | None, Decimal | None, Decimal | None]


def _parse_columns(line: Line, columns: list[str]) -> Parsed | None:
    """Map the trailing numbers to the header's columns. None if the row has too few numbers."""
    spans = find_amount_spans(line.text)
    if len(columns) < 2 or len(spans) < len(columns) or "total" not in columns:
        return None
    tail = spans[-len(columns) :]
    description = line.text[: tail[0][0]].strip(" -:|x×@\t")
    if sum(ch.isalpha() for ch in description) < 2:
        return None
    values = {}
    for kind, (_, raw, parsed) in zip(columns, tail, strict=True):
        values.setdefault(kind, parse_quantity(raw) if kind == "qty" else parsed.value)
    return description, values.get("qty"), values.get("unit"), values.get("total")


def _parse_at(line: Line) -> Parsed | None:
    match = _AT_LINE.match(line.text.strip())
    if not match:
        return None
    unit = find_amounts(match.group("unit"))
    total = find_amounts(match.group("total"))
    qty_raw = match.group("lead_qty") or match.group("trail_qty")
    if not unit or not total:
        return None
    description = match.group("desc").strip(" -:|")
    if match.group("lead_qty") and match.group("trail"):  # "2 x Oat milk 1L": "1L" is the pack size
        description += match.group("trail")
    if sum(ch.isalpha() for ch in description) < 2:
        return None
    return (
        description,
        parse_quantity(qty_raw) if qty_raw else Decimal(1),
        unit[-1][1].value,
        total[-1][1].value,
    )


def _parse_item(line: Line) -> Parsed | None:
    """(description, quantity, unit_price, total) from one line, or None if it isn't an item line."""
    if "@" in line.text and (at := _parse_at(line)):
        return at
    text = line.text
    spans = find_amount_spans(text)
    if not spans:
        return None
    # The numeric columns are the trailing numbers; anything earlier belongs to the description
    # ("Model 2000 printer  1  199.00  199.00").
    columns = spans[-3:]
    description = text[: columns[0][0]].strip(" -:|@\t")
    raws = [raw for _, raw, _ in columns]
    values = [parsed.value for _, _, parsed in columns]
    glued = _TRAILING_QTY.match(description)
    if len(values) == 2 and glued:  # "Widget assembly kit 4x 12.50 50.00"
        return glued.group("desc").strip(" -:|"), Decimal(glued.group("qty")), values[0], values[1]
    description = description.strip(" x×")
    if sum(ch.isalpha() for ch in description) < 2:
        return None
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


def _is_continuation(line: Line, columns: list[str]) -> bool:
    """Wrapped description text: no column gap and fewer numbers than the table has columns."""
    if len(line.text) >= 120 or _COLUMN_GAP.search(line.text) or re.search(r"\d[.,]\d{2}$", line.text):
        return False  # a row ending in an amount is a row, even when OCR lost the column gaps
    return len(find_amount_spans(line.text)) < max(len(columns), 1)


def extract_line_items(lines: list[Line], *, targets: Sequence[Decimal] = ()) -> list[LineItemResult]:
    header_at = next((i for i, line in enumerate(lines) if is_table_header(line)), None)
    items: list[LineItemResult] = []

    if header_at is not None:
        columns = header_columns(lines[header_at])
        for line in lines[header_at + 1 :]:
            if _SUMMARY.search(line.text):
                break
            if is_table_header(line):  # table header repeated on the next page
                continue
            parsed = None
            if not _has_date(line.text):
                parsed = _parse_columns(line, columns) or (
                    None if items and _is_continuation(line, columns) else _parse_item(line)
                )
            if parsed is None:
                # Wrapped description: text-only lines, or short lines that don't fill the columns.
                if items and (not find_amounts(line.text) or _is_continuation(line, columns)):
                    items[-1].description = f"{items[-1].description} {line.text}".strip()[:500]
                continue
            items.append(_make_item(parsed, line, in_table=True))
        return items

    # No header. Candidate lines: above the first total line, not dates, with a money-like last amount.
    candidates: list[tuple[Parsed, Line]] = []
    for line in lines:
        if _TOTAL_LINE.search(line.text):
            break
        if _SUMMARY.search(line.text) or _has_date(line.text):
            continue
        parsed = _parse_item(line)
        spans = find_amount_spans(line.text)
        if parsed and parsed[3] is not None and spans and re.search(r"[.,]\d{2}$", spans[-1][1]):
            candidates.append((parsed, line))

    proven = [(p, ln) for p, ln in candidates if _consistent(p[1], p[2], p[3])]
    if candidates and len(candidates) > len(proven):
        total = sum((p[3] for p, _ in candidates), Decimal("0"))  # type: ignore[misc]
        if any(abs(total - target) <= Decimal("0.01") for target in targets):
            return [_make_item(p, ln, in_table=False, sum_checked=True) for p, ln in candidates]
    return [_make_item(p, ln, in_table=False) for p, ln in proven]


def _make_item(parsed: Parsed, line: Line, *, in_table: bool, sum_checked: bool = False) -> LineItemResult:
    description, qty, unit, total = parsed
    arithmetic = _consistent(qty, unit, total)
    return LineItemResult(
        description=description[:500],
        quantity=qty,
        unit_price=unit,
        total=total,
        confidence=confidence.line_item_confidence(
            # Rows confirmed by the document's own total are as trustworthy as table rows.
            in_table=in_table or sum_checked,
            arithmetic_ok=arithmetic,
            ocr_confidence=line.ocr_confidence,
        ),
        page_number=line.page_number,
        raw=line.text,
    )
