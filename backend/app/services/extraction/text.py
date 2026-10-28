"""Layer 1: text normalization.

OCR output confuses look-alike characters (O/0, l/1/I, S/5). Two tools handle that
without rewriting the document text:

- ``fuzzy_label`` builds regexes for *labels* ("Total", "Invoice No") that tolerate
  those confusions ("T0tal", "lnvoice").
- ``repair_numeric_token`` fixes confusions *inside tokens that are already mostly
  digits* ("54.0O" → "54.00"). It is applied only to candidate values, and the
  original text is what gets stored as the field's raw value.
"""

import re
import unicodedata
from dataclasses import dataclass

_CONFUSABLE = {
    "o": "[o0]",
    "0": "[o0]",
    "i": "[il1|!]",
    "l": "[il1|!]",
    "1": "[il1|]",
    "s": "[s5$]",
    "e": "[ec]",
    "b": "[b8]",
    "g": "[g9]",
}


def fuzzy_label(*words: str) -> str:
    """Regex for a multi-word label tolerant of OCR confusions and flexible spacing/punctuation."""
    parts = []
    for word in words:
        chars = []
        for ch in word.lower():
            if ch in _CONFUSABLE:
                chars.append(_CONFUSABLE[ch])
            elif ch.isalpha():
                chars.append(f"[{ch}{ch.upper()}]")
            else:
                chars.append(re.escape(ch))
        parts.append("".join(chars))
    return r"[\s._-]*".join(parts)


_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
_SPACE_CHARS = re.compile(r"[\t  -​]")
_GAPS = re.compile(r" {3,}")  # keep column gaps visible as exactly two spaces


def normalize_text(text: str) -> str:
    """Unicode-normalize, unify dashes and spaces, drop empty lines. Line order is kept."""
    text = unicodedata.normalize("NFKC", text).translate(_DASHES)
    lines = (_GAPS.sub("  ", _SPACE_CHARS.sub(" ", line)).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"})
_NUMERICISH = re.compile(r"^[\d.,\s'OoDlI|SB]+$")


def repair_numeric_token(token: str) -> str:
    """Fix OCR letter/digit confusions in a token that is mostly digits; leave other tokens alone."""
    stripped = token.strip()
    digits = sum(ch.isdigit() for ch in stripped)
    if (
        not stripped
        or not _NUMERICISH.match(stripped)
        or digits < max(1, len(stripped.replace(" ", "")) // 2)
    ):
        return token
    return stripped.translate(_DIGIT_FIXES)


@dataclass(frozen=True)
class Line:
    page_number: int
    index: int  # position within the page
    text: str
    ocr_confidence: float | None  # page-level OCR confidence (None for text-layer pages)


def split_lines(pages) -> list[Line]:  # pages: Iterable[PageText]
    lines: list[Line] = []
    for page in pages:
        for index, text in enumerate(normalize_text(page.text or "").splitlines()):
            lines.append(Line(page.page_number, index, text, page.ocr_confidence))
    return lines
