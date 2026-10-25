"""Tesseract OCR via pytesseract (which shells out to the tesseract binary)."""

import os
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytesseract

from app.services.ocr.base import OCRError, OCRResult, OCRService, OCRUnavailableError, OCRWord

# Default location used by the UB-Mannheim Windows installer (winget UB-Mannheim.TesseractOCR).
_WINDOWS_DEFAULT = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe"
)


def resolve_tesseract_cmd(configured: str) -> str | None:
    if configured:
        return configured if Path(configured).is_file() or shutil.which(configured) else None
    if found := shutil.which("tesseract"):
        return found
    return str(_WINDOWS_DEFAULT) if _WINDOWS_DEFAULT.is_file() else None


class TesseractOCR(OCRService):
    name = "tesseract"

    def __init__(self, *, cmd: str = "", language: str = "eng", timeout_seconds: int = 60) -> None:
        self._cmd = resolve_tesseract_cmd(cmd)
        self.language = language
        self.timeout_seconds = timeout_seconds

    def _require_cmd(self) -> str:
        if not self._cmd:
            raise OCRUnavailableError("Tesseract executable not found (set TESSERACT_CMD).")
        # pytesseract reads a module-level global; set it right before each call.
        pytesseract.pytesseract.tesseract_cmd = self._cmd
        return self._cmd

    def check_available(self) -> str:
        self._require_cmd()
        try:
            return f"tesseract {pytesseract.get_tesseract_version()}"
        except (pytesseract.TesseractNotFoundError, OSError) as exc:
            raise OCRUnavailableError("Tesseract executable could not be run.") from exc

    def extract_text(self, image: np.ndarray, *, page_number: int) -> OCRResult:
        self._require_cmd()
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.language,
                config="--oem 1 --psm 3",  # LSTM engine, automatic page segmentation
                output_type=pytesseract.Output.DICT,
                timeout=self.timeout_seconds,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OCRUnavailableError("Tesseract executable could not be run.") from exc
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            raise OCRError(f"Tesseract timed out after {self.timeout_seconds}s") from exc
        except pytesseract.TesseractError as exc:
            raise OCRError(f"Tesseract failed (status {exc.status})") from exc

        words: list[OCRWord] = []
        line_ids: dict[tuple[int, int, int], int] = {}
        for i, raw in enumerate(data["text"]):
            text = raw.strip()
            if not text:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            line = line_ids.setdefault(key, len(line_ids))
            conf = float(data["conf"][i])
            words.append(
                OCRWord(
                    text=text,
                    confidence=conf / 100 if conf >= 0 else None,
                    bbox=(data["left"][i], data["top"][i], data["width"][i], data["height"][i]),
                    line=line,
                )
            )

        lines: dict[int, list[str]] = defaultdict(list)
        for word in words:
            lines[word.line].append(word.text)
        text = "\n".join(" ".join(lines[i]) for i in sorted(lines))

        confidences = [w.confidence for w in words if w.confidence is not None]
        confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
        return OCRResult(page_number=page_number, text=text, confidence=confidence, words=words)
