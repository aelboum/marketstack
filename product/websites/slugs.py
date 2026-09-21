"""Slug normalization/validation, shared by `Website.slug` and
`Page.slug` (docs/ROADMAP.md Phase 11.1).

**Normalization is narrow: case-folding only, never silent rewriting.**
A slug is lower-cased (the one transformation applied) and then
validated against a closed character set -- it is never "cleaned up" by
stripping invalid characters, collapsing whitespace into hyphens, or
similar. This is a deliberate choice: a slug is a public, memorable
identifier a tenant chose on purpose; silently mangling
`"My Page!!"` into `"my-page"` would let two different inputs collide
unpredictably and would surprise a caller who typed something invalid
expecting a clear error, not a guess. `WebsiteValidationError` is raised
for anything that does not already conform once lower-cased.

**Character set and length**: `^[a-z0-9]+(-[a-z0-9]+)*$`, 1-63
characters -- lowercase alphanumeric segments separated by single
hyphens, never a leading/trailing/doubled hyphen. 63 is a deliberate
bound, not an arbitrary round number: it is the maximum length of a
single DNS label (RFC 1035), chosen so a website slug remains usable as
a subdomain component if that is ever wired up later (this phase does
not wire it up -- see `product/websites/models.py::Website`'s own module
docstring on the custom-domain boundary) without needing to be
re-validated against a *different*, stricter bound at that point.

**Uniqueness scope is enforced at the database layer, not here** -- this
module only shapes and validates the string; `Website.slug`'s global
`UNIQUE` constraint and `Page`'s `UniqueConstraint(tenant_id, website_id,
slug)` (`product/websites/models.py`) are the actual collision guarantee,
enforced under concurrent creation the way every other uniqueness
constraint in this codebase already is -- a normalized-but-colliding slug
surfaces as `product.websites.errors.WebsiteSlugTakenError`
(`product/websites/websites.py`/`pages.py`), translated from the real
constraint violation, never a racy SELECT-then-INSERT check.
"""

from __future__ import annotations

import re

from product.websites.errors import WebsiteValidationError

MIN_SLUG_LENGTH = 1
MAX_SLUG_LENGTH = 63

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def normalize_slug(raw: str) -> str:
    """Lower-cases `raw` and validates it against the closed slug
    character set and length bound. Raises `WebsiteValidationError` for
    anything that does not conform once lower-cased; returns the
    normalized (lower-cased) slug otherwise."""
    if not isinstance(raw, str):
        raise WebsiteValidationError("slug must be a string.")
    normalized = raw.lower()
    if not (MIN_SLUG_LENGTH <= len(normalized) <= MAX_SLUG_LENGTH):
        raise WebsiteValidationError(
            f"slug must be between {MIN_SLUG_LENGTH} and {MAX_SLUG_LENGTH} characters."
        )
    if not _SLUG_PATTERN.fullmatch(normalized):
        raise WebsiteValidationError(
            "slug must contain only lowercase letters, digits, and single hyphens "
            "(no leading, trailing, or doubled hyphen)."
        )
    return normalized


__all__ = ["MAX_SLUG_LENGTH", "MIN_SLUG_LENGTH", "normalize_slug"]
