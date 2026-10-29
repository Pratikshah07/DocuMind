import cv2
import numpy as np
import pytest

from app.services.image_service import load_image
from app.services.preprocessing_service import STEPS, Preprocessor, estimate_skew
from tests.samples import make_photo_jpeg, render_text_image


@pytest.fixture(scope="module")
def page() -> np.ndarray:
    return np.asarray(render_text_image(dpi=100))


def rotate(image: np.ndarray, degrees: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), borderValue=(255, 255, 255))


@pytest.mark.parametrize("name", sorted(STEPS))
def test_every_step_leaves_its_input_untouched(page: np.ndarray, name: str) -> None:
    original = page.copy()
    result = STEPS[name](page)
    assert np.array_equal(page, original)
    assert result is not page


def test_grayscale_contrast_denoise_return_single_channel(page: np.ndarray) -> None:
    for name in ("grayscale", "contrast", "denoise", "threshold"):
        assert STEPS[name](page).ndim == 2, name


def test_threshold_is_binary(page: np.ndarray) -> None:
    assert set(np.unique(STEPS["threshold"](page))) <= {0, 255}


def test_resize_normalizes_working_width(page: np.ndarray) -> None:
    assert STEPS["resize"](page[:200, :400]).shape[1] == 1200  # upscale capped at 3x
    assert STEPS["resize"](np.full((100, 1800, 3), 255, np.uint8)).shape[1] == 1800  # in range: unchanged
    assert STEPS["resize"](np.full((4000, 3000), 255, np.uint8)).shape == (2667, 2000)  # phone photo: down


@pytest.mark.parametrize("degrees", [-10, -4, 2, 6, 12])
def test_skew_is_estimated_and_corrected(page: np.ndarray, degrees: float) -> None:
    skewed = rotate(page, degrees)
    assert estimate_skew(skewed) == pytest.approx(degrees, abs=0.5)
    assert estimate_skew(STEPS["deskew"](skewed)) == pytest.approx(0, abs=0.5)


@pytest.mark.parametrize("degrees", [-6, 4, 9])
def test_skew_estimate_survives_uneven_lighting_and_noise(degrees: float) -> None:
    # Regression: a global (Otsu) threshold read the shadow gradient as ink and returned ~18°.
    photo = np.asarray(load_image(make_photo_jpeg(angle=degrees), max_pixels=40_000_000))
    assert estimate_skew(photo) == pytest.approx(degrees, abs=0.5)


def test_deskew_ignores_blank_pages_and_implausible_angles(page: np.ndarray) -> None:
    blank = np.full((500, 400), 255, np.uint8)
    assert np.array_equal(STEPS["deskew"](blank), blank)
    sideways = rotate(page, 30)  # beyond the 15° correction limit: left alone
    assert np.array_equal(STEPS["deskew"](sideways), sideways)


def test_preprocessor_applies_steps_in_order(page: np.ndarray) -> None:
    result = Preprocessor(["grayscale", "threshold"]).run(page)
    assert result.ndim == 2 and set(np.unique(result)) <= {0, 255}
    assert Preprocessor([]).run(page).shape == page.shape  # no steps: unchanged copy


def test_unknown_step_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="sharpen"):
        Preprocessor(["grayscale", "sharpen"])


def test_run_tracked_reports_rotation() -> None:
    from app.services.preprocessing_service import Preprocessor
    from tests.samples import make_photo_jpeg, render_text_image

    straight = Preprocessor(["grayscale", "deskew"]).run_tracked(render_text_image())
    assert straight[1] is False
    import io

    from PIL import Image

    skewed = Image.open(io.BytesIO(make_photo_jpeg(angle=4.0)))
    assert Preprocessor(["grayscale", "deskew"]).run_tracked(skewed)[1] is True
