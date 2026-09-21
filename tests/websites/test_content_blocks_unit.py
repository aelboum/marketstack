"""The closed, bounded content-block vocabulary (docs/ROADMAP.md Phase
11.1, product/websites/content_blocks.py). No database -- a plain unit
test, part of the default `pytest` run.

Security-relevant: this module is the structural XSS mitigation for
website pages (no raw-HTML block type at all), so these tests include
the adversarial payloads a real attacker would try against `button.url`
and the free-text fields.
"""

from __future__ import annotations

import pytest
from product.websites.content_blocks import (
    BLOCK_TYPES,
    MAX_ALT_TEXT_CHARS,
    MAX_ASSET_REF_CHARS,
    MAX_BLOCKS_PER_PAGE,
    MAX_BUTTON_TEXT_CHARS,
    MAX_HEADING_TEXT_CHARS,
    MAX_PARAGRAPH_TEXT_CHARS,
    MAX_URL_CHARS,
    validate_content_blocks,
)
from product.websites.errors import WebsiteValidationError


def test_empty_list_is_valid() -> None:
    validate_content_blocks([])  # must not raise


def test_rejects_non_list() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks({"type": "heading", "text": "Hi"})


def test_rejects_too_many_blocks() -> None:
    blocks = [{"type": "spacer"} for _ in range(MAX_BLOCKS_PER_PAGE + 1)]
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(blocks)


def test_accepts_exactly_max_blocks() -> None:
    blocks = [{"type": "spacer"} for _ in range(MAX_BLOCKS_PER_PAGE)]
    validate_content_blocks(blocks)  # must not raise


def test_rejects_non_object_block() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(["not-a-dict"])


def test_rejects_unknown_block_type() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "raw_html", "html": "<b>x</b>"}])


def test_block_types_has_no_raw_html_variant() -> None:
    # Structural XSS mitigation: no HTML/script/iframe/embed block type
    # exists in the vocabulary at all.
    assert "html" not in BLOCK_TYPES
    assert "script" not in BLOCK_TYPES
    assert "embed" not in BLOCK_TYPES
    assert "iframe" not in BLOCK_TYPES
    assert BLOCK_TYPES == {"heading", "paragraph", "image", "button", "spacer"}


# --- heading -------------------------------------------------------------


def test_heading_valid() -> None:
    validate_content_blocks([{"type": "heading", "text": "Welcome", "level": 2}])


def test_heading_defaults_level_to_1() -> None:
    validate_content_blocks([{"type": "heading", "text": "Welcome"}])


def test_heading_requires_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "heading"}])


def test_heading_rejects_empty_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "heading", "text": ""}])


def test_heading_rejects_oversized_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "heading", "text": "a" * (MAX_HEADING_TEXT_CHARS + 1)}])


def test_heading_accepts_max_text() -> None:
    validate_content_blocks([{"type": "heading", "text": "a" * MAX_HEADING_TEXT_CHARS}])


@pytest.mark.parametrize("level", [0, 4, -1, "1", 1.5, True])
def test_heading_rejects_invalid_level(level: object) -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "heading", "text": "Hi", "level": level}])


@pytest.mark.parametrize("level", [1, 2, 3])
def test_heading_accepts_valid_levels(level: int) -> None:
    validate_content_blocks([{"type": "heading", "text": "Hi", "level": level}])


def test_heading_rejects_control_characters() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "heading", "text": "Hi\x00there"}])


def test_heading_allows_newline_and_tab() -> None:
    validate_content_blocks([{"type": "heading", "text": "Hi\nthere\ttab"}])


def test_heading_text_containing_script_tag_is_accepted_as_inert_text() -> None:
    """A `<script>` payload in a plain text field is accepted as long as
    it stays within bounds -- never executed, since no renderer path in
    this phase ever interprets a text field as HTML (module docstring:
    "stored and later rendered as plain text"). Proves the payload
    survives as a harmless string, not that it is stripped or escaped
    here (escaping is the frontend renderer's job at render time)."""
    validate_content_blocks([{"type": "heading", "text": "<script>alert(1)</script>", "level": 1}])


# --- paragraph -------------------------------------------------------------


def test_paragraph_valid() -> None:
    validate_content_blocks([{"type": "paragraph", "text": "Body copy."}])


def test_paragraph_rejects_oversized_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(
            [{"type": "paragraph", "text": "a" * (MAX_PARAGRAPH_TEXT_CHARS + 1)}]
        )


def test_paragraph_rejects_non_string_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "paragraph", "text": 12345}])


# --- image -------------------------------------------------------------


def test_image_valid() -> None:
    validate_content_blocks(
        [{"type": "image", "asset_ref": "tenant/abc/logo.png", "alt_text": "Logo"}]
    )


def test_image_alt_text_is_optional() -> None:
    validate_content_blocks([{"type": "image", "asset_ref": "tenant/abc/logo.png"}])


def test_image_requires_asset_ref() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "image", "alt_text": "Logo"}])


def test_image_rejects_oversized_asset_ref() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "image", "asset_ref": "a" * (MAX_ASSET_REF_CHARS + 1)}])


def test_image_rejects_oversized_alt_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(
            [
                {
                    "type": "image",
                    "asset_ref": "ref",
                    "alt_text": "a" * (MAX_ALT_TEXT_CHARS + 1),
                }
            ]
        )


# --- button (the XSS-relevant block type) -----------------------------------


def test_button_valid_https() -> None:
    validate_content_blocks(
        [{"type": "button", "text": "Learn more", "url": "https://example.com/pricing"}]
    )


def test_button_valid_http() -> None:
    validate_content_blocks([{"type": "button", "text": "Go", "url": "http://example.com"}])


def test_button_valid_relative_path() -> None:
    validate_content_blocks([{"type": "button", "text": "Go", "url": "/pricing"}])


def test_button_requires_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "button", "url": "https://example.com"}])


def test_button_requires_url() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "button", "text": "Go"}])


def test_button_rejects_oversized_text() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(
            [
                {
                    "type": "button",
                    "text": "a" * (MAX_BUTTON_TEXT_CHARS + 1),
                    "url": "https://example.com",
                }
            ]
        )


def test_button_rejects_oversized_url() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(
            [
                {
                    "type": "button",
                    "text": "Go",
                    "url": "https://example.com/" + "a" * MAX_URL_CHARS,
                }
            ]
        )


@pytest.mark.parametrize(
    "payload",
    [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)",
        "javascript:/*comment*/alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "JAVASCRIPT:alert(1)",
    ],
)
def test_button_rejects_unsafe_url_schemes(payload: str) -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "button", "text": "Go", "url": payload}])


def test_button_rejects_scheme_with_no_host() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "button", "text": "Go", "url": "https:///pricing"}])


def test_button_rejects_non_string_url() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "button", "text": "Go", "url": 12345}])


# --- spacer -------------------------------------------------------------


def test_spacer_valid() -> None:
    validate_content_blocks([{"type": "spacer"}])


def test_spacer_rejects_extra_fields() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": "spacer", "height": 40}])


# --- mixed / malformed input -------------------------------------------------------------


def test_multiple_valid_blocks_mixed_types() -> None:
    validate_content_blocks(
        [
            {"type": "heading", "text": "Welcome", "level": 1},
            {"type": "paragraph", "text": "Intro copy."},
            {"type": "image", "asset_ref": "ref-1"},
            {"type": "button", "text": "Sign up", "url": "/signup"},
            {"type": "spacer"},
        ]
    )


def test_one_invalid_block_among_valid_ones_still_rejects_whole_list() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks(
            [
                {"type": "heading", "text": "Welcome"},
                {"type": "button", "text": "Go", "url": "javascript:alert(1)"},
            ]
        )


def test_rejects_missing_type_field() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"text": "Hi"}])


def test_rejects_null_type_field() -> None:
    with pytest.raises(WebsiteValidationError):
        validate_content_blocks([{"type": None, "text": "Hi"}])
