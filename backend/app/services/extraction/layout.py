"""Field locations: where on the page an extracted value was printed.

The extractor works on text lines; the page reader keeps each page's words with their
boxes (exact for the PDF text layer; Tesseract's for OCR pages that were not rotated).
A field's raw value is matched against consecutive words on its page. A box is stored
only when the value occurs exactly once there: "USD" or "1.00" printed several times
gets no box rather than a possibly wrong one.
"""

from collections.abc import Mapping, Sequence

from app.services.extraction.types import FieldResult

Word = tuple[str, float, float, float, float]  # text, x0, y0, x1, y1 (0–1 of the page)
_EDGE_PUNCTUATION = " ,;:()[]\"'"


def _token(text: str) -> str:
    return text.strip(_EDGE_PUNCTUATION).casefold()


def find_box(value: str, words: Sequence[Word]) -> list[float] | None:
    tokens = [t for t in (_token(part) for part in value.split()) if t]
    if not tokens or not words:
        return None
    normalized = [_token(w[0]) for w in words]
    hits = [i for i in range(len(words) - len(tokens) + 1) if normalized[i : i + len(tokens)] == tokens]
    if len(hits) != 1:
        return None
    span = words[hits[0] : hits[0] + len(tokens)]
    box = [min(w[1] for w in span), min(w[2] for w in span), max(w[3] for w in span), max(w[4] for w in span)]
    return [round(min(1.0, max(0.0, v)), 4) for v in box]


def locate_fields(fields: Mapping[str, FieldResult], words_by_page: Mapping[int, Sequence[Word]]) -> None:
    """Set ``bbox`` on every extracted (not user-entered) field whose value is found exactly once."""
    for f in fields.values():
        f.bbox = None
        if f.user_edited or f.value is None or f.page_number is None:
            continue
        f.bbox = find_box(f.value, words_by_page.get(f.page_number, ()))
