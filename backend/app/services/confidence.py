"""Confidence scoring: a transparent heuristic in [0, 1], NOT a calibrated probability (D8).

Stored confidence (at extraction time):

    base(method) × context(label strength) × format(flags) × ocr_factor

    base      label-anchored 0.95 · positional pattern 0.70 · user-entered 1.0
    context   strong label ("Invoice Date") 1.0 · weak label ("Date") 0.85 · pattern 1.0 (base covers it)
    format    × 0.70 per ambiguity flag (ambiguous date/amount, conflicting candidates); invalid → 0.15
    ocr       text-layer page 1.0 · OCR'd page 0.6 + 0.4 × engine confidence

Effective confidence (at read/validation time) additionally applies consistency:
a field named in a cross-field warning (e.g. totals don't add up) × 0.70. This is
computed from the *current* warnings rather than stored, so re-validating after an
edit is idempotent.
"""

from collections.abc import Iterable

from app.services.extraction.types import (
    FLAG_AMBIGUOUS_AMOUNT,
    FLAG_AMBIGUOUS_DATE,
    FLAG_INVALID_FORMAT,
    FLAG_MULTIPLE_CANDIDATES,
    METHOD_LABEL,
    METHOD_PATTERN,
    METHOD_RULE,
    METHOD_USER,
)

_BASE = {METHOD_LABEL: 0.95, METHOD_PATTERN: 0.70, METHOD_RULE: 0.90, METHOD_USER: 1.0}
_CONTEXT = {"strong": 1.0, "weak": 0.85, "pattern": 1.0}
_FLAG_PENALTY = 0.70
_PENALIZED_FLAGS = {FLAG_AMBIGUOUS_DATE, FLAG_AMBIGUOUS_AMOUNT, FLAG_MULTIPLE_CANDIDATES}
_INVALID = 0.15
_CONSISTENCY_PENALTY = 0.70


def ocr_factor(ocr_confidence: float | None) -> float:
    return 1.0 if ocr_confidence is None else 0.6 + 0.4 * max(0.0, min(1.0, ocr_confidence))


def extraction_confidence(
    *, method: str, label_strength: str, ocr_confidence: float | None, flags: Iterable[str]
) -> float:
    flags = set(flags)
    if FLAG_INVALID_FORMAT in flags:
        return _INVALID
    score = _BASE.get(method, 0.5) * _CONTEXT.get(label_strength, 1.0) * ocr_factor(ocr_confidence)
    for _ in flags & _PENALIZED_FLAGS:
        score *= _FLAG_PENALTY
    return round(max(0.0, min(1.0, score)), 3)


def line_item_confidence(
    *, in_table: bool, arithmetic_ok: bool | None, ocr_confidence: float | None
) -> float:
    score = 0.90 if in_table else 0.75
    if arithmetic_ok is False:
        score *= 0.60
    return round(score * ocr_factor(ocr_confidence), 3)


def effective_confidence(stored: float | None, *, inconsistent: bool) -> float | None:
    if stored is None:
        return None
    return round(stored * (_CONSISTENCY_PENALTY if inconsistent else 1.0), 3)


def level(score: float | None, *, high: float, medium: float) -> str | None:
    """'high' / 'medium' / 'low' for display; thresholds come from settings."""
    if score is None:
        return None
    return "high" if score >= high else "medium" if score >= medium else "low"
