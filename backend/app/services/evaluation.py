"""Extraction quality measured against hand-labelled ground truth (samples/ground_truth.json).

Pure scoring, no I/O. The numbers it produces describe *these synthetic samples only*;
they are not a general accuracy claim.

Field scoring, per labelled field (``"__skip__"`` = not scored):
- expected value, same value extracted → correct
- expected value, different or no value → wrong (a miss or a misread)
- expected null, nothing extracted → correct (true negative)
- expected null, something extracted → false positive

Values are compared after normalization: amounts as decimals, dates as ISO strings, text
case-insensitively with whitespace collapsed (tax IDs also ignore spaces and hyphens).

Line items: an expected row is matched to an extracted row with the same total and the
best description match (each extracted row used once). Row precision/recall come from
the matches; cell accuracy is description/quantity/unit price/total over matched rows.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

SKIP = "__skip__"
_AMOUNT_FIELDS = {"subtotal", "tax", "discount", "total"}
_ID_FIELDS = {"vendor_tax_id"}


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def same_value(name: str, expected: Any, got: Any) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    if name in _AMOUNT_FIELDS:
        return _dec(expected) == _dec(got)
    if name in _ID_FIELDS:
        return re.sub(r"[\s-]", "", str(expected)).lower() == re.sub(r"[\s-]", "", str(got)).lower()
    return _norm_text(expected) == _norm_text(got)


@dataclass
class FieldScore:
    name: str
    expected: Any
    got: Any
    correct: bool

    @property
    def kind(self) -> str:
        if self.correct:
            return "correct"
        if self.expected is None:
            return "false_positive"
        return "missed" if self.got is None else "misread"


@dataclass
class SampleScore:
    sample: str
    type_correct: bool
    fields: list[FieldScore] = field(default_factory=list)
    rows_expected: int = 0
    rows_extracted: int = 0
    rows_matched: int = 0
    cells_correct: int = 0
    cells_total: int = 0

    @property
    def field_errors(self) -> list[FieldScore]:
        return [f for f in self.fields if not f.correct]


def score_sample(
    sample: str,
    truth: dict[str, Any],
    *,
    document_type: str,
    fields: dict[str, Any],
    line_items: list[dict[str, Any]],
) -> SampleScore:
    """``fields``: name → normalized value as the API returns it (ISO date, number, text)."""
    result = SampleScore(sample, document_type == truth["document_type"])
    for name, expected in truth["fields"].items():
        if expected == SKIP:
            continue
        got = fields.get(name)
        result.fields.append(FieldScore(name, expected, got, same_value(name, expected, got)))

    expected_rows = truth.get("line_items", [])
    result.rows_expected, result.rows_extracted = len(expected_rows), len(line_items)
    unused = list(range(len(line_items)))
    for row in expected_rows:
        candidates = [i for i in unused if _dec(line_items[i].get("total")) == _dec(row["total"])]
        if not candidates:
            continue
        best = max(
            candidates,
            key=lambda i: same_value("description", row["description"], line_items[i].get("description")),
        )
        unused.remove(best)
        result.rows_matched += 1
        got = line_items[best]
        for cell in ("description", "quantity", "unit_price", "total"):
            result.cells_total += 1
            exp, val = row.get(cell), got.get(cell)
            ok = same_value(cell, exp, val) if cell == "description" else _dec(exp) == _dec(val)
            result.cells_correct += ok
    return result


@dataclass
class Summary:
    samples: int
    type_accuracy: float
    fields_scored: int
    fields_correct: int
    present_fields: int  # expected a value
    present_correct: int
    false_positives: int
    row_precision: float | None
    row_recall: float | None
    cell_accuracy: float | None


def summarize(scores: list[SampleScore]) -> Summary:
    fields = [f for s in scores for f in s.fields]
    present = [f for f in fields if f.expected is not None]
    expected_rows = sum(s.rows_expected for s in scores)
    extracted_rows = sum(s.rows_extracted for s in scores)
    matched = sum(s.rows_matched for s in scores)
    cells = sum(s.cells_total for s in scores)
    return Summary(
        samples=len(scores),
        type_accuracy=sum(s.type_correct for s in scores) / len(scores) if scores else 0.0,
        fields_scored=len(fields),
        fields_correct=sum(f.correct for f in fields),
        present_fields=len(present),
        present_correct=sum(f.correct for f in present),
        false_positives=sum(f.kind == "false_positive" for f in fields),
        row_precision=matched / extracted_rows if extracted_rows else None,
        row_recall=matched / expected_rows if expected_rows else None,
        cell_accuracy=sum(s.cells_correct for s in scores) / cells if cells else None,
    )


def resolve_truth(all_truth: dict[str, Any], sample: str) -> dict[str, Any]:
    truth = all_truth[sample]
    return all_truth[truth["same_as"]] if "same_as" in truth else truth
