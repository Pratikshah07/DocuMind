"""Configurable image preprocessing before OCR (OpenCV).

Steps are named, ordered and chosen per source type (see Settings
``preprocess_pdf_steps`` / ``preprocess_image_steps``); none is applied blindly.
Every step returns a new array, so the input (and the stored original file) are never modified.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

Array = np.ndarray
Step = Callable[[Array], Array]

# Working width for camera images. Tesseract works best when capital letters are ~20–40 px tall:
# narrow crops are upscaled; large phone photos (4000 px+) are downscaled, because beyond this width
# OCR gains nothing and denoising time grows with pixel count (measured: 12 MP 10.7 s → 2000 px 1.8 s).
_MIN_WIDTH = 1600
_MAX_WIDTH = 2000
_MAX_UPSCALE = 3.0
# Skew corrections outside this range are more likely misdetections than real skew.
_MIN_SKEW_DEG = 0.3
_MAX_SKEW_DEG = 15.0
_SKEW_WORK_WIDTH = 800


def _to_gray(image: Array) -> Array:
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image.copy()


def resize(image: Array) -> Array:
    """Bring the width into [_MIN_WIDTH, _MAX_WIDTH]: upscale narrow crops (max 3x), downscale huge photos."""
    width = image.shape[1]
    if width < _MIN_WIDTH:
        scale, interpolation = min(_MIN_WIDTH / width, _MAX_UPSCALE), cv2.INTER_CUBIC
    elif width > _MAX_WIDTH:
        scale, interpolation = _MAX_WIDTH / width, cv2.INTER_AREA
    else:
        return image.copy()
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=interpolation)


def grayscale(image: Array) -> Array:
    return _to_gray(image)


def denoise(image: Array) -> Array:
    """Non-local-means denoise: removes sensor/JPEG noise while keeping stroke edges.

    Median/Gaussian blurs were measured as useless here (0/5 noisy photos readable vs 5/5);
    searchWindowSize=11 (OpenCV default 21) is ~3x faster with the same accuracy.
    """
    gray = _to_gray(image)
    return cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=11)


def contrast(image: Array) -> Array:
    """CLAHE: evens out uneven lighting (shadows across a photographed receipt)."""
    gray = _to_gray(image)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def threshold(image: Array) -> Array:
    """Adaptive (local) binarization.

    Needed for photos: Tesseract's built-in global binarization returns nothing on
    pages with uneven lighting plus noise. Not used for rendered PDF pages, which are already clean.
    """
    gray = _to_gray(image)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def _rotate(image: Array, degrees: float, *, border: int | tuple[int, int, int], flags: int) -> Array:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)  # positive = counter-clockwise
    return cv2.warpAffine(
        image, matrix, (width, height), flags=flags, borderMode=cv2.BORDER_CONSTANT, borderValue=border
    )


def estimate_skew(image: Array) -> float:
    """Skew in degrees (positive = rotated counter-clockwise) by the projection-profile method.

    Ink pixels are rotated through candidate angles; when text lines are level,
    the row sums of ink alternate sharply between lines and gaps, so the
    variance of the horizontal projection peaks. Coarse 1° search, then 0.1° refinement.
    """
    gray = _to_gray(image)
    scale = min(1.0, _SKEW_WORK_WIDTH / gray.shape[1])  # work on a small copy: ~ms per angle
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # Local (adaptive) threshold: a global one turns shadows and lighting gradients into "ink".
    gray = cv2.medianBlur(gray, 3)  # drop sensor-noise speckles
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    if cv2.countNonZero(ink) < 0.002 * ink.size:  # blank page: nothing to align
        return 0.0

    def sharpness(angle: float) -> float:
        rotated = _rotate(ink, angle, border=0, flags=cv2.INTER_NEAREST)
        return float(np.var(rotated.sum(axis=1, dtype=np.float64)))

    limit = _MAX_SKEW_DEG + 2  # search a little past the correction limit so large skews aren't clamped in
    coarse = max(np.arange(-limit, limit + 0.5, 1.0), key=sharpness)
    best = max(np.arange(coarse - 1.0, coarse + 1.05, 0.1), key=sharpness)
    # Rotating by `best` levels the text, so the page is skewed by -best.
    return round(float(-best), 2) + 0.0  # + 0.0 turns -0.0 into 0.0


def deskew(image: Array) -> Array:
    angle = estimate_skew(image)
    if not (_MIN_SKEW_DEG <= abs(angle) <= _MAX_SKEW_DEG):
        return image.copy()
    border = 255 if image.ndim == 2 else (255, 255, 255)
    return _rotate(image, -angle, border=border, flags=cv2.INTER_CUBIC)


STEPS: dict[str, Step] = {
    "resize": resize,
    "grayscale": grayscale,
    "denoise": denoise,
    "contrast": contrast,
    "threshold": threshold,
    "deskew": deskew,
}


@dataclass
class Preprocessor:
    steps: Sequence[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        unknown = [s for s in self.steps if s not in STEPS]
        if unknown:
            raise ValueError(f"Unknown preprocessing steps: {unknown}. Known: {sorted(STEPS)}")

    def run(self, image: Image.Image | Array) -> Array:
        array = np.asarray(image.convert("RGB")) if isinstance(image, Image.Image) else image
        for name in self.steps:
            array = STEPS[name](array)
        return array
