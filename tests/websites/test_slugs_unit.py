"""Slug normalization/validation (docs/ROADMAP.md Phase 11.1,
product/websites/slugs.py). No database -- a plain unit test, part of the
default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.websites.errors import WebsiteValidationError
from product.websites.slugs import MAX_SLUG_LENGTH, MIN_SLUG_LENGTH, normalize_slug


def test_lowercase_is_folded() -> None:
    assert normalize_slug("My-Page") == "my-page"


def test_already_lowercase_is_unchanged() -> None:
    assert normalize_slug("my-page-2") == "my-page-2"


def test_case_variants_normalize_to_the_same_slug() -> None:
    assert normalize_slug("Landing") == normalize_slug("LANDING") == normalize_slug("landing")


def test_rejects_non_string() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug(123)  # type: ignore[arg-type]


def test_rejects_empty_string() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("")


def test_rejects_spaces() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("my page")


def test_rejects_leading_hyphen() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("-my-page")


def test_rejects_trailing_hyphen() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("my-page-")


def test_rejects_doubled_hyphen() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("my--page")


def test_rejects_underscore() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("my_page")


def test_rejects_unicode_confusable() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("my‐page")  # U+2010 HYPHEN, not ASCII '-'


def test_rejects_non_ascii_letters() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("café")


def test_never_silently_strips_invalid_characters() -> None:
    # Deliberately not "my-page" -- normalize_slug() must raise, not clean up.
    with pytest.raises(WebsiteValidationError):
        normalize_slug("My Page!!")


def test_rejects_exceeding_max_length() -> None:
    with pytest.raises(WebsiteValidationError):
        normalize_slug("a" * (MAX_SLUG_LENGTH + 1))


def test_accepts_exactly_max_length() -> None:
    slug = "a" * MAX_SLUG_LENGTH
    assert normalize_slug(slug) == slug


def test_accepts_exactly_min_length() -> None:
    slug = "a" * MIN_SLUG_LENGTH
    assert normalize_slug(slug) == slug


def test_accepts_digits_only() -> None:
    assert normalize_slug("12345") == "12345"


def test_accepts_single_char() -> None:
    assert normalize_slug("a") == "a"
