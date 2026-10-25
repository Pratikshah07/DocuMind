import pytest

from app.services.image_service import load_image
from app.services.processing_errors import ProcessingError
from tests.samples import make_jpeg, make_png, make_rotated_exif_jpeg, make_tiny_png, truncate

MAX_PIXELS = 40_000_000


@pytest.mark.parametrize("data", [make_png(), make_jpeg(), make_tiny_png()], ids=["png", "jpeg", "tiny-png"])
def test_decodes_supported_images_to_rgb(data: bytes) -> None:
    image = load_image(data, max_pixels=MAX_PIXELS)
    assert image.mode == "RGB"
    assert image.width > 0 and image.height > 0


def test_applies_exif_orientation() -> None:
    image = load_image(make_rotated_exif_jpeg(), max_pixels=MAX_PIXELS)
    assert image.size == (200, 400)  # stored 400x200, Orientation=6 → upright portrait


@pytest.mark.parametrize(
    "data",
    [
        truncate(make_jpeg(), 0.5),
        truncate(make_png(), 0.5),
        make_png()[:60],  # signature + partial header
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        b"\xff\xd8\xff\xe0garbage",
    ],
    ids=["truncated-jpeg", "truncated-png", "png-header-only", "png-garbage", "jpeg-garbage"],
)
def test_damaged_images_are_rejected(data: bytes) -> None:
    with pytest.raises(ProcessingError) as exc:
        load_image(data, max_pixels=MAX_PIXELS)
    assert exc.value.code == "corrupt_image"


def test_pixel_budget_is_enforced_before_decoding() -> None:
    with pytest.raises(ProcessingError) as exc:
        load_image(make_png(), max_pixels=1000)
    assert exc.value.code == "image_too_large"
