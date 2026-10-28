"""Document classification (invoice / receipt / unknown).

``DocumentClassifier`` is the seam: an ML or LLM classifier can replace or wrap
``RuleBasedClassifier`` later. The rule-based one scores weighted keyword
evidence; the confidence is a documented heuristic (D8), not a probability.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.models import DocumentType
from app.services.extraction.text import fuzzy_label, normalize_text
from app.services.extraction.types import Classification, PageText

# (regex, weight). Each signal counts once, however often it appears.
_INVOICE_SIGNALS = [
    (fuzzy_label("invoice"), 3.0),
    (fuzzy_label("invoice") + r"[\s.]*(?:n[o0]|number|num|#)", 2.0),
    (fuzzy_label("bill", "to"), 2.0),
    (fuzzy_label("due", "date") + "|" + fuzzy_label("payment", "due"), 2.0),
    (fuzzy_label("amount", "due") + "|" + fuzzy_label("balance", "due"), 1.5),
    (r"\b(?:payment\s+terms|terms|net\s?\d{1,3})\b", 1.0),
    (r"\b(?:remit|bank\s+details|iban|swift|account\s+number)\b", 1.0),
    (r"\b(?:purchase\s+order|p\.?o\.?\s*(?:no|number|#))\b", 1.0),
    (fuzzy_label("ship", "to"), 1.0),
]
_RECEIPT_SIGNALS = [
    (fuzzy_label("receipt"), 3.0),
    (r"\b(?:cashier|server|register|terminal|till|store\s*#?)\b", 2.0),
    (r"\bchange(?:\s+due)?\b", 1.5),
    (r"\b(?:cash|card\s+tendered|tendered|approved|auth(?:orization)?\s+code)\b", 1.5),
    (r"\b(?:visa|mastercard|amex|debit|credit\s+card|contactless)\b", 1.0),
    (r"\bthank\s+you\b", 1.0),
    (r"\b(?:table|guests?|tip|gratuity)\b", 1.0),
]
_COMMON_SIGNALS = [  # money documents in general; they don't pick a side
    (fuzzy_label("subtotal") + "|" + fuzzy_label("sub", "total"), 0.5),
    (r"\b(?:tax|vat|gst|hst)\b", 0.5),
    (fuzzy_label("total"), 0.5),
]

_MIN_SCORE = 3.0  # below this, it is not recognisably an invoice or a receipt


class DocumentClassifier(ABC):
    @abstractmethod
    def classify(self, pages: Sequence[PageText]) -> Classification: ...


def _score(text: str, signals: list[tuple[str, float]]) -> float:
    return sum(weight for pattern, weight in signals if re.search(pattern, text, re.IGNORECASE))


class RuleBasedClassifier(DocumentClassifier):
    def classify(self, pages: Sequence[PageText]) -> Classification:
        text = normalize_text("\n".join(p.text or "" for p in pages))
        common = _score(text, _COMMON_SIGNALS)
        invoice = _score(text, _INVOICE_SIGNALS) + common
        receipt = _score(text, _RECEIPT_SIGNALS) + common
        scores = {"invoice": invoice, "receipt": receipt}

        best_type, best, other = (
            (DocumentType.INVOICE, invoice, receipt)
            if invoice >= receipt
            else (DocumentType.RECEIPT, receipt, invoice)
        )
        if best < _MIN_SCORE:
            # Confident it's *not* a recognisable invoice/receipt only when evidence is near zero.
            return Classification(DocumentType.UNKNOWN, round(1.0 - best / _MIN_SCORE * 0.5, 3), scores)

        # More evidence → higher; a close second-best → lower.
        strength = min(1.0, 0.55 + 0.05 * best)
        margin = (best - other) / best
        confidence = strength * (0.75 + 0.25 * margin)
        return Classification(best_type, round(min(confidence, 0.98), 3), scores)
