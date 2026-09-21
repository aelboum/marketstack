"""The closed, bounded page-content-block vocabulary (docs/ROADMAP.md
Phase 11.1's own "block-based" page builder).

**A closed set of five block types, nothing else -- no raw HTML block,
no script block, no iframe/embed block, no plugin system.** Every block
is a small, typed, bounded structure; every text field is stored and
later rendered as plain text (a future frontend renders each field as a
typed prop, never `dangerouslySetInnerHTML`-shaped raw markup), so there
is no HTML-injection surface to begin with -- this is a stronger
guarantee than sanitizing untrusted HTML, because there is no HTML
accepted in the first place. The one field that could otherwise carry an
XSS payload despite being "just text" is a link URL (`button.url`):
`_validate_link_url()` rejects `javascript:`/`data:`/`vbscript:` and any
other non-`http(s)`/non-relative scheme, the standard mitigation for
"attacker-controlled `href`" (distinct from, and narrower than,
`product/automation/actions.py::_validate_webhook_url()`'s own SSRF
protection -- that guards a server-side fetch this module never performs;
this guards a link a browser will later follow, so DNS/IP-literal
resolution is irrelevant here and deliberately not checked).

**Bounded, not unbounded** -- `MAX_BLOCKS_PER_PAGE` caps how many blocks
one page may hold; every text field has its own bounded max length. A
`content_blocks` value is validated by `validate_content_blocks()` before
it is ever persisted (`product/websites/pages.py`), so an oversized or
malformed value never reaches the database in the first place.

**`image.asset_ref` is a bounded identifier only, not yet backed by a
real upload flow.** `product/foundation/storage.py`'s own `ObjectStorage`
abstraction is this product's one sanctioned object-storage interface
(never a second implementation), and this field is shaped to eventually
hold a `tenant_scoped_key()`-style reference into it -- but no website
asset-upload endpoint exists in this phase (deferred, not silently
narrowed; see this package's own module docstring). Validated here only
for bounded length and a safe character set, not for pointing at a real,
existing object.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from product.websites.errors import WebsiteValidationError

BLOCK_TYPE_HEADING = "heading"
BLOCK_TYPE_PARAGRAPH = "paragraph"
BLOCK_TYPE_IMAGE = "image"
BLOCK_TYPE_BUTTON = "button"
BLOCK_TYPE_SPACER = "spacer"

BLOCK_TYPES = frozenset(
    {
        BLOCK_TYPE_HEADING,
        BLOCK_TYPE_PARAGRAPH,
        BLOCK_TYPE_IMAGE,
        BLOCK_TYPE_BUTTON,
        BLOCK_TYPE_SPACER,
    }
)

MAX_BLOCKS_PER_PAGE = 100
MAX_HEADING_TEXT_CHARS = 200
MAX_PARAGRAPH_TEXT_CHARS = 4_000
MAX_ALT_TEXT_CHARS = 300
MAX_ASSET_REF_CHARS = 512
MAX_BUTTON_TEXT_CHARS = 100
MAX_URL_CHARS = 2_048

_SAFE_URL_SCHEMES = frozenset({"http", "https"})


def _require_bounded_str(
    block: Mapping[str, object], field: str, *, max_chars: int, required: bool
) -> str | None:
    raw = block.get(field)
    if raw is None:
        if required:
            raise WebsiteValidationError(f"block.{field} is required.")
        return None
    if not isinstance(raw, str):
        raise WebsiteValidationError(f"block.{field} must be a string.")
    if required and not raw:
        raise WebsiteValidationError(f"block.{field} must not be empty.")
    if len(raw) > max_chars:
        raise WebsiteValidationError(f"block.{field} exceeds {max_chars} characters.")
    if any(ord(ch) < 0x20 and ch not in ("\n", "\t") for ch in raw):
        raise WebsiteValidationError(f"block.{field} contains a disallowed control character.")
    return raw


def _validate_link_url(url: str) -> None:
    """Rejects any scheme except `http`/`https`, and a relative path (no
    scheme, no netloc) -- the two shapes a safe `<a href>` may take.
    `javascript:`, `data:`, `vbscript:`, and every other scheme are
    refused outright, regardless of case or whitespace tricks (`urlparse`
    itself normalizes scheme casing)."""
    parsed = urlparse(url.strip())
    if parsed.scheme and parsed.scheme.lower() not in _SAFE_URL_SCHEMES:
        raise WebsiteValidationError(
            f"block.url uses a disallowed scheme {parsed.scheme!r}; "
            f"only http, https, or a relative path are allowed."
        )
    if parsed.scheme and not parsed.netloc:
        raise WebsiteValidationError("block.url has a scheme but no host.")


def _validate_heading(block: Mapping[str, object]) -> None:
    _require_bounded_str(block, "text", max_chars=MAX_HEADING_TEXT_CHARS, required=True)
    level = block.get("level", 1)
    if not isinstance(level, int) or isinstance(level, bool) or level < 1 or level > 3:
        raise WebsiteValidationError("block.level must be an integer between 1 and 3.")


def _validate_paragraph(block: Mapping[str, object]) -> None:
    _require_bounded_str(block, "text", max_chars=MAX_PARAGRAPH_TEXT_CHARS, required=True)


def _validate_image(block: Mapping[str, object]) -> None:
    _require_bounded_str(block, "asset_ref", max_chars=MAX_ASSET_REF_CHARS, required=True)
    _require_bounded_str(block, "alt_text", max_chars=MAX_ALT_TEXT_CHARS, required=False)


def _validate_button(block: Mapping[str, object]) -> None:
    _require_bounded_str(block, "text", max_chars=MAX_BUTTON_TEXT_CHARS, required=True)
    url = _require_bounded_str(block, "url", max_chars=MAX_URL_CHARS, required=True)
    assert url is not None  # required=True guarantees non-None
    _validate_link_url(url)


def _validate_spacer(block: Mapping[str, object]) -> None:
    extra = set(block) - {"type"}
    if extra:
        raise WebsiteValidationError(f"block type 'spacer' accepts no fields, got {sorted(extra)}.")


_VALIDATORS = {
    BLOCK_TYPE_HEADING: _validate_heading,
    BLOCK_TYPE_PARAGRAPH: _validate_paragraph,
    BLOCK_TYPE_IMAGE: _validate_image,
    BLOCK_TYPE_BUTTON: _validate_button,
    BLOCK_TYPE_SPACER: _validate_spacer,
}


def validate_content_blocks(blocks: object) -> None:
    """Validates a whole `content_blocks` value -- a bounded list of
    bounded, typed blocks. Raises `WebsiteValidationError` for anything
    that does not conform; returns `None` when the value is usable.
    Called at page create/update time, before the value is ever
    persisted."""
    if not isinstance(blocks, list):
        raise WebsiteValidationError("content_blocks must be a list.")
    if len(blocks) > MAX_BLOCKS_PER_PAGE:
        raise WebsiteValidationError(f"content_blocks exceeds {MAX_BLOCKS_PER_PAGE} blocks.")
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            raise WebsiteValidationError(f"content_blocks[{index}] must be an object.")
        block_type = block.get("type")
        if block_type not in BLOCK_TYPES:
            raise WebsiteValidationError(
                f"content_blocks[{index}].type must be one of {sorted(BLOCK_TYPES)}, "
                f"got {block_type!r}."
            )
        _VALIDATORS[block_type](block)


__all__ = [
    "BLOCK_TYPES",
    "BLOCK_TYPE_BUTTON",
    "BLOCK_TYPE_HEADING",
    "BLOCK_TYPE_IMAGE",
    "BLOCK_TYPE_PARAGRAPH",
    "BLOCK_TYPE_SPACER",
    "MAX_ALT_TEXT_CHARS",
    "MAX_ASSET_REF_CHARS",
    "MAX_BLOCKS_PER_PAGE",
    "MAX_BUTTON_TEXT_CHARS",
    "MAX_HEADING_TEXT_CHARS",
    "MAX_PARAGRAPH_TEXT_CHARS",
    "MAX_URL_CHARS",
    "validate_content_blocks",
]
