"""OCR interface. The pipeline depends on this, never on a specific engine."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class OCRWord:
    text: str
    confidence: float | None  # 0–1, engine-reported
    bbox: tuple[int, int, int, int]  # left, top, width, height in pixels of the OCR'd image
    line: int  # reading-order line index, for reassembly


@dataclass(frozen=True)
class OCRResult:
    page_number: int
    text: str
    # Mean word confidence (0–1) as reported by the engine; None when the engine reports none.
    confidence: float | None
    words: list[OCRWord] = field(default_factory=list)


class OCRError(Exception):
    """The engine ran but failed (crash, timeout, unreadable output)."""


class OCRUnavailableError(OCRError):
    """The engine is not installed or not configured."""


class OCRService(ABC):
    name: str

    @abstractmethod
    def extract_text(self, image: np.ndarray, *, page_number: int) -> OCRResult: ...

    @abstractmethod
    def check_available(self) -> str:
        """Return a short version string, or raise OCRUnavailableError."""
