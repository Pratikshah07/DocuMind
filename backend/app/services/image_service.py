"""Image decoding with Pillow: full decode (not just headers), EXIF orientation, size guards."""

import io
import warnings

from PIL import Image, ImageOps

from app.services.processing_errors import ProcessingError, corrupt_image

_FORMATS = ("PNG", "JPEG")


def load_image(content: bytes, *, max_pixels: int) -> Image.Image:
    """Decode a PNG/JPEG into an upright RGB image. Raises ProcessingError for bad input."""
    try:
        with warnings.catch_warnings():
            # Pillow warns (not errors) between 1x and 2x MAX_IMAGE_PIXELS; we enforce our own limit.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(content), formats=_FORMATS)
            width, height = probe.size
            if width * height > max_pixels:
                raise ProcessingError(
                    "image_too_large",
                    "The image resolution is too large to process.",
                    detail=f"{width}x{height}",
                )
            probe.verify()  # structural check (checksums, chunk order); the object is unusable afterwards

            image = Image.open(io.BytesIO(content), formats=_FORMATS)
            image.load()  # full decode: catches truncated pixel data that verify() misses for JPEG
    except ProcessingError:
        raise
    except Image.DecompressionBombError as exc:
        raise ProcessingError("image_too_large", "The image resolution is too large to process.") from exc
    except Exception as exc:  # UnidentifiedImageError, OSError("image file is truncated"), SyntaxError, ...
        raise corrupt_image(type(exc).__name__) from exc

    image = ImageOps.exif_transpose(image)  # phone photos store rotation in EXIF
    if image.width == 0 or image.height == 0:
        raise ProcessingError("empty_document", "The image has no pixels.")
    return image.convert("RGB")
