"""Field locations (bounding boxes) on the page."""

from app.services.extraction.layout import find_box, locate_fields
from app.services.extraction.types import FieldResult

WORDS = [
    ("Total", 0.1, 0.5, 0.2, 0.52),
    ("Due:", 0.21, 0.5, 0.26, 0.52),
    ("USD", 0.3, 0.5, 0.34, 0.52),
    ("4,820.00", 0.35, 0.5, 0.45, 0.52),
    ("Paid", 0.1, 0.6, 0.15, 0.62),
    ("USD", 0.3, 0.6, 0.34, 0.62),
]


def test_unique_multi_word_value_gets_the_union_box() -> None:
    assert find_box("Total Due", WORDS) == [0.1, 0.5, 0.26, 0.52]
    assert find_box("4,820.00", WORDS) == [0.35, 0.5, 0.45, 0.52]


def test_value_printed_twice_gets_no_box() -> None:
    assert find_box("USD", WORDS) is None


def test_missing_or_user_entered_values_get_no_box() -> None:
    fields = {
        "total": FieldResult("total", "4,820.00", page_number=1),
        "currency": FieldResult("currency", "USD", page_number=1, user_edited=True),
        "tax": FieldResult("tax"),
    }
    locate_fields(fields, {1: WORDS})
    assert fields["total"].bbox == [0.35, 0.5, 0.45, 0.52]
    assert fields["currency"].bbox is None and fields["tax"].bbox is None
