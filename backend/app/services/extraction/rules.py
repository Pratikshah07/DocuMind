"""Layers 2–3: deterministic field extraction (label regexes + positional patterns).

Every value keeps the exact text it came from (``FieldResult.value``). Nothing is
computed or defaulted: a field that is not in the document stays missing, and a
label whose value can't be parsed yields an *invalid* field, not a guess.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.models import DocumentType
from app.services import confidence
from app.services.extraction.line_items import extract_line_items, is_table_header
from app.services.extraction.parsers import (
    SPACE_GROUPED,
    DateOrder,
    find_amounts,
    find_currencies,
    find_date,
    parse_amount,
)
from app.services.extraction.text import Line, split_lines
from app.services.extraction.text import fuzzy_label as fz
from app.services.extraction.types import (
    FIELD_NAMES,
    FLAG_AMBIGUOUS_AMOUNT,
    FLAG_AMBIGUOUS_DATE,
    FLAG_INVALID_FORMAT,
    FLAG_MULTIPLE_CANDIDATES,
    METHOD_LABEL,
    METHOD_PATTERN,
    FieldResult,
    LineItemResult,
    PageText,
)

STRONG, WEAK = "strong", "weak"
# Label/value separator. A '-' directly before a digit is a sign ("Discount -13.50"), not a separator.
_SEP = r"\s*(?:[:#.]|-(?!\s?\d))*\s*"


class FieldExtractor(ABC):
    """Replaceable extraction provider (an NLP/LLM-backed one can implement the same interface)."""

    @abstractmethod
    def extract(
        self, pages: Sequence[PageText], document_type: DocumentType
    ) -> tuple[dict[str, FieldResult], list[LineItemResult]]: ...


@dataclass
class _Candidate:
    raw: str
    normalized: object
    line: Line
    strength: str
    priority: int = 0
    flags: set[str] = field(default_factory=set)
    notes: dict[str, str] = field(default_factory=dict)
    label: str = ""


def _label(pattern: str, *, anywhere: bool = False) -> re.Pattern[str]:
    """Label → value. Generic labels ("Total", "Date") must start a line or follow a column gap;
    specific multi-word ones ("Due date", "Amount due") may appear mid-line."""
    prefix = r"\b" if anywhere else r"(?:^|\s{2,}|\|\s*)"
    return re.compile(rf"{prefix}(?P<label>{pattern}){_SEP}(?P<rest>.*)$", re.IGNORECASE)


# --- Label catalogues -------------------------------------------------------

_INVOICE_NO = [
    (_label(fz("invoice") + r"\s*(?:n[o0]\.?|number|num|#|id)"), STRONG),
    (_label(r"inv\.?\s*(?:n[o0]\.?|#)"), STRONG),
    (_label(r"(?:receipt|order|transaction|trans|bill|document|doc)\s*(?:n[o0]\.?|number|num|#|id)"), STRONG),
    (_label(fz("invoice")), WEAK),  # "INVOICE  INV-2041"
    (_label(r"(?:reference|ref)\.?(?:\s*(?:n[o0]\.?|#))?"), WEAK),
]
_INVOICE_DATE = [
    (_label(r"(?:" + fz("invoice") + r"|bill|receipt|issue|transaction)\s*date", anywhere=True), STRONG),
    (_label(r"date\s+of\s+(?:issue|invoice)|issued(?:\s+on)?|dated", anywhere=True), STRONG),
    (_label(r"(?<!due\s)(?<!due)" + fz("date")), WEAK),
]
_DUE_DATE = [
    (_label(r"due\s*date|payment\s+due|due\s+(?:by|on)|pay\s+by", anywhere=True), STRONG),
    (_label(r"due"), WEAK),
]
_VENDOR = [(_label(r"vendor|seller|supplier|sold\s+by|merchant|billed\s+by|from|company"), STRONG)]
_BILLING = [(_label(r"bill(?:ed)?\s+to|billing\s+address|sold\s+to|customer"), STRONG)]
_SHIPPING = [(_label(r"ship(?:ped)?\s+to|shipping\s+address|deliver(?:y|ed)?\s+(?:to|address)"), STRONG)]

# Amount labels: (pattern, priority). Higher priority wins when several match.
_TOTAL = [
    (
        _label(
            r"grand\s*" + fz("total") + r"|" + fz("total") + r"\s*(?:due|payable|amount)|"
            r"amount\s*(?:due|payable)|balance\s*due|invoice\s*" + fz("total"),
            anywhere=True,
        ),
        2,
    ),
    (
        _label(
            r"(?<!sub)(?<!sub\s)(?<!sub-)"
            + fz("total")
            + r"(?!\s*(?:tax|vat|gst|items?|qty|quantity|discount|savings))"
        ),
        1,
    ),
]
_SUBTOTAL = [(_label(fz("subtotal") + "|" + fz("sub", "total") + r"|net\s+amount"), 1)]
_TAX = [
    (
        _label(
            r"(?:sales\s+)?(?:tax|vat|gst|hst|pst|cgst|sgst|igst)(?:\s*\(?[\d.]+\s*%\)?)?(?!\s*(?:id|no|number|#|reg))"
        ),
        1,
    )
]
_DISCOUNT = [(_label(r"(?:less\s+)?discount|promo(?:tion)?|coupon|savings"), 1)]

_PAYMENT_LABEL = _label(r"payment\s+(?:method|type)|paid\s+(?:by|via|with)|tender(?:ed)?|card\s+type")
_PAYMENT_METHODS = [  # (regex, canonical name). The raw value stored is the matched word, never card digits.
    (r"\bvisa\b", "Visa"),
    (r"\bmaster\s?card\b|\bmc\b", "Mastercard"),
    (r"\bamex\b|\bamerican\s+express\b", "American Express"),
    (r"\bdiscover\b", "Discover"),
    (r"\bdebit(?:\s+card)?\b", "Debit card"),
    (r"\bcredit\s+card\b", "Credit card"),
    (r"\bupi\b", "UPI"),
    (r"\bpaypal\b", "PayPal"),
    (r"\b(?:bank|wire)\s+transfer\b|\bach\b|\bneft\b|\bimps\b", "Bank transfer"),
    (r"\bcash\b", "Cash"),
]

_TITLE_ONLY = re.compile(
    r"^(?:tax\s+|sales\s+|commercial\s+|proforma\s+)?(?:invoice|receipt|bill|statement)\W*$", re.I
)
_ANY_LABEL = re.compile(
    r"(?:invoice|date|due|total|subtotal|tax|bill\s+to|ship\s+to|amount|balance|payment|qty|quantity|"
    r"description|phone|tel|email|www\.|http)",
    re.I,
)
_INVOICE_NO_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9\-/._]{0,39}", re.I)


def _rest_or_next(lines: list[Line], i: int, rest: str) -> tuple[str, Line]:
    """Value after the label; if empty, the next line on the same page ("Invoice Number\\nINV-1")."""
    rest = rest.strip()
    if rest or i + 1 >= len(lines) or lines[i + 1].page_number != lines[i].page_number:
        return rest, lines[i]
    return lines[i + 1].text.strip(), lines[i + 1]


class RuleBasedExtractor(FieldExtractor):
    def __init__(self, *, date_order: DateOrder = DateOrder.DMY) -> None:
        self.date_order = date_order

    def extract(
        self, pages: Sequence[PageText], document_type: DocumentType
    ) -> tuple[dict[str, FieldResult], list[LineItemResult]]:
        lines = split_lines(pages)
        fields = {name: FieldResult(name) for name in FIELD_NAMES}
        self._pick(fields, "invoice_number", self._invoice_numbers(lines))
        self._pick(fields, "invoice_date", self._dates(lines, _INVOICE_DATE, exclude_due=True))
        self._pick(fields, "due_date", self._dates(lines, _DUE_DATE))
        for name, labels in (
            ("subtotal", _SUBTOTAL),
            ("tax", _TAX),
            ("discount", _DISCOUNT),
            ("total", _TOTAL),
        ):
            self._pick(
                fields, name, self._amounts(lines, labels), prefer_last=True, sum_distinct=(name == "tax")
            )
        self._pick(fields, "vendor_name", self._vendors(lines))
        self._pick(fields, "billing_address", self._address(lines, _BILLING))
        self._pick(fields, "shipping_address", self._address(lines, _SHIPPING))
        self._pick(fields, "payment_method", self._payment(lines))
        self._pick(fields, "currency", self._currency(lines))
        if fields["invoice_date"].is_missing:
            self._pick(fields, "invoice_date", self._first_date(lines))
        _discount_as_positive(fields["discount"])
        return fields, extract_line_items(lines)

    # --- Selection ---

    def _pick(
        self,
        fields: dict[str, FieldResult],
        name: str,
        candidates: list[_Candidate],
        *,
        prefer_last: bool = False,
        sum_distinct: bool = False,
    ) -> None:
        if not candidates:
            return
        top = max(c.priority for c in candidates)
        best_group = [c for c in candidates if c.priority == top]
        strong = [c for c in best_group if c.strength == STRONG] or best_group
        distinct = {str(c.normalized) for c in strong if c.normalized is not None}

        flags: set[str] = set()
        notes: dict[str, str] = {}
        by_label = {_label_key(c.label): c for c in strong if c.normalized is not None}  # last per label
        if sum_distinct and len(by_label) > 1 and len(by_label) == len(strong):
            # Separately labelled taxes (CGST 9% + SGST 9%): the document's own components, so add
            # them up, even when the amounts are equal. Each label appears exactly once.
            parts = list(by_label.values())
            total = sum((c.normalized for c in parts), Decimal("0"))  # type: ignore[misc]
            raw = " + ".join(c.raw for c in parts)
            chosen = _Candidate(
                raw, total, parts[0].line, STRONG, top, set().union(*(c.flags for c in parts))
            )
            notes["summed_from"] = " + ".join(f"{c.label} {c.raw}" for c in parts)
        else:
            chosen = strong[-1] if prefer_last else strong[0]
            if len(distinct) > 1:
                flags.add(FLAG_MULTIPLE_CANDIDATES)
                notes["candidates"] = ", ".join(sorted(distinct))

        result = fields[name]
        result.value = chosen.raw
        result.normalized = chosen.normalized  # type: ignore[assignment]
        result.method = METHOD_PATTERN if chosen.strength == "pattern" else METHOD_LABEL
        result.page_number = chosen.line.page_number
        result.flags = chosen.flags | flags
        result.notes = chosen.notes | notes
        result.confidence = confidence.extraction_confidence(
            method=result.method,
            label_strength=chosen.strength,
            ocr_confidence=chosen.line.ocr_confidence,
            flags=result.flags,
        )

    # --- Field finders ---

    def _matches(self, lines: list[Line], labels):  # yields (index, line, label_match, strength_or_priority)
        for i, line in enumerate(lines):
            for pattern, tag in labels:
                match = pattern.search(line.text)
                if match:
                    yield i, line, match, tag
                    break

    def _invoice_numbers(self, lines: list[Line]) -> list[_Candidate]:
        found = []
        for i, _, match, strength in self._matches(lines, _INVOICE_NO):
            rest, source = _rest_or_next(lines, i, match.group("rest"))
            token = _INVOICE_NO_TOKEN.match(rest)
            if not token or not re.search(r"\d", token.group()):
                continue
            as_date = find_date(token.group(), self.date_order)
            if as_date and as_date[0] == token.group():  # the "number" is just a date ("Invoice 2025-03-18")
                continue
            value = token.group().rstrip(".-/")
            found.append(_Candidate(value, value, source, strength, label=match.group("label")))
        return found

    def _dates(self, lines: list[Line], labels, *, exclude_due: bool = False) -> list[_Candidate]:
        found = []
        for i, line, match, strength in self._matches(lines, labels):
            if exclude_due and re.search(r"\bdue\b", line.text[: match.end("label")], re.I):
                continue
            rest, source = _rest_or_next(lines, i, match.group("rest"))
            date_found = find_date(rest, self.date_order)
            if date_found is None:
                if rest and re.search(r"\d", rest):  # label + something date-like that isn't a valid date
                    found.append(_Candidate(rest[:40], None, source, strength, flags={FLAG_INVALID_FORMAT}))
                continue
            raw, parsed = date_found
            if parsed is None:  # e.g. 31/02/2025
                found.append(_Candidate(raw, None, source, strength, flags={FLAG_INVALID_FORMAT}))
                continue
            flags, notes = set(), {}
            if parsed.ambiguous:
                flags.add(FLAG_AMBIGUOUS_DATE)
                notes["alternative"] = parsed.alternative or ""
            found.append(_Candidate(raw, parsed.value, source, strength, flags=flags, notes=notes))
        return found

    def _first_date(self, lines: list[Line]) -> list[_Candidate]:
        """Fallback: the first date in the document that is not on a due-date line."""
        for line in lines:
            if re.search(r"\bdue\b|\bexp(?:iry|ires)?\b|\bvalid\b", line.text, re.I):
                continue
            date_found = find_date(line.text, self.date_order)
            if date_found and date_found[1] is not None:
                raw, parsed = date_found
                flags = {FLAG_AMBIGUOUS_DATE} if parsed.ambiguous else set()
                notes = {"alternative": parsed.alternative} if parsed.ambiguous and parsed.alternative else {}
                return [_Candidate(raw, parsed.value, line, "pattern", flags=flags, notes=notes)]
        return []

    def _amounts(self, lines: list[Line], labels) -> list[_Candidate]:
        found = []
        for i, line, match, priority in self._matches(lines, labels):
            if is_table_header(line):  # "Description  Qty  Price  Total" names a column, not a value
                continue
            rest, source = _rest_or_next(lines, i, match.group("rest"))
            if source is not line and sum(ch.isalpha() for ch in rest) > 3:
                continue  # label alone on its line: accept the next line only if it is just an amount
            spaced = SPACE_GROUPED.match(rest.strip())
            spaced_value = parse_amount(spaced.group(1)) if spaced else None
            amounts = [(spaced.group(1), spaced_value)] if spaced and spaced_value else find_amounts(rest)
            if not amounts:
                if re.search(r"\d", rest):  # a labelled total we cannot read as a number
                    found.append(_Candidate(rest[:40], None, source, STRONG, priority, {FLAG_INVALID_FORMAT}))
                continue
            raw, parsed = amounts[-1]  # rightmost number on the line is the amount column
            flags = {FLAG_AMBIGUOUS_AMOUNT} if parsed.ambiguous else set()
            notes = {"alternative": parsed.alternative} if parsed.ambiguous and parsed.alternative else {}
            found.append(
                _Candidate(
                    raw, parsed.value, source, STRONG, priority, flags, notes, label=match.group("label")
                )
            )
        return found

    def _vendors(self, lines: list[Line]) -> list[_Candidate]:
        labelled = []
        for i, _, match, strength in self._matches(lines, _VENDOR):
            rest, source = _rest_or_next(lines, i, match.group("rest"))
            if _looks_like_name(rest):
                labelled.append(_Candidate(rest[:120], rest[:120], source, strength))
        if labelled:
            return labelled
        # Pattern: the first name-like line near the top of the first page (letterhead).
        first_page = lines[0].page_number if lines else 1
        for line in [ln for ln in lines if ln.page_number == first_page][:6]:
            text = line.text.strip(" -|")
            if _TITLE_ONLY.match(text) or not _looks_like_name(text) or _ANY_LABEL.search(text):
                continue
            return [_Candidate(text[:120], text[:120], line, "pattern")]
        return []

    def _address(self, lines: list[Line], labels) -> list[_Candidate]:
        for i, line, match, strength in self._matches(lines, labels):
            parts = [match.group("rest").strip()] if match.group("rest").strip() else []
            for nxt in lines[i + 1 : i + 6]:
                if nxt.page_number != line.page_number or len(parts) >= 4:
                    break
                starts_new_section = bool(_ANY_LABEL.search(nxt.text)) and not nxt.text[:1].isdigit()
                is_summary_line = bool(find_amounts(nxt.text)) and bool(
                    re.search(r"total|tax|due", nxt.text, re.I)
                )
                if starts_new_section or is_summary_line:
                    break
                parts.append(nxt.text.strip())
            if parts:
                value = ", ".join(parts)[:300]
                return [_Candidate(value, value, line, strength)]
        return []

    def _payment(self, lines: list[Line]) -> list[_Candidate]:
        ordered = [ln for ln in lines if _PAYMENT_LABEL.search(ln.text)] + lines  # labelled lines first
        for line in ordered:
            strength = STRONG if _PAYMENT_LABEL.search(line.text) else "pattern"
            for pattern, canonical in _PAYMENT_METHODS:
                match = re.search(pattern, line.text, re.I)
                if match:
                    return [_Candidate(match.group(), canonical, line, strength)]
        return []

    def _currency(self, lines: list[Line]) -> list[_Candidate]:
        mentions = [(raw, code, line) for line in lines for raw, code in find_currencies(line.text)]
        if not mentions:
            return []
        codes = [code for _, code, _ in mentions]
        explicit = [m for m in mentions if m[0] == m[1]]  # ISO code written out beats a symbol
        raw, code, line = (explicit or mentions)[0]
        flags, notes = set(), {}
        if len(set(codes)) > 1:
            flags.add(FLAG_MULTIPLE_CANDIDATES)
            notes["candidates"] = ", ".join(sorted(set(codes)))
        # "$" alone doesn't say which dollar: weaker evidence than a written code.
        strength = STRONG if explicit or raw not in ("$",) else WEAK
        return [_Candidate(raw, code, line, strength, flags=flags, notes=notes)]


def _label_key(label: str) -> str:
    return re.sub(r"\W+", " ", label.lower()).strip()


def _looks_like_name(text: str) -> bool:
    letters = sum(ch.isalpha() for ch in text)
    return (
        3 <= len(text) <= 80
        and letters >= 3
        and letters / max(len(text), 1) >= 0.5
        and not text[:1].isdigit()
    )


def _discount_as_positive(discount: FieldResult) -> None:
    # Discounts are printed as "-5.00" or "(5.00)"; the field means "amount taken off", so store magnitude.
    # The raw value keeps the sign exactly as printed.
    if isinstance(discount.normalized, Decimal) and discount.normalized < 0:
        discount.normalized = -discount.normalized
