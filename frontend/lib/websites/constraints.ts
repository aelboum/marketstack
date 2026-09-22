// Real backend limits, mirrored so the UI can reject an out-of-range
// value immediately instead of waiting on a round-trip 400 -- same
// discipline as `lib/automation/constraints.ts`/`lib/reputation/
// constraints.ts`: validate against the backend's own constant, never an
// arbitrary client-invented cap.

/** `product/websites/models.py::MAX_WEBSITE_NAME_LENGTH`. */
export const MAX_WEBSITE_NAME_LENGTH = 255;

/** `product/websites/slugs.py::MAX_SLUG_LENGTH` (also
 * `product/websites/models.py::MAX_SLUG_LENGTH`) -- shared by both
 * `Website.slug` and `Page.slug`. */
export const MAX_SLUG_LENGTH = 63;

/** `product/websites/slugs.py::_SLUG_PATTERN` --
 * `^[a-z0-9]+(-[a-z0-9]+)*$`. The backend lower-cases before validating
 * and never rewrites otherwise, so this is a hint only -- the backend's
 * own error message is shown verbatim on a real mismatch. */
export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** `product/websites/models.py::MAX_CUSTOM_DOMAIN_LENGTH`. */
export const MAX_CUSTOM_DOMAIN_LENGTH = 255;

/** `product/websites/models.py::MAX_PAGE_TITLE_LENGTH`. */
export const MAX_PAGE_TITLE_LENGTH = 255;

/** `product/websites/content_blocks.py::MAX_BLOCKS_PER_PAGE`. */
export const MAX_BLOCKS_PER_PAGE = 100;

/** `product/websites/content_blocks.py::MAX_HEADING_TEXT_CHARS`. */
export const MAX_HEADING_TEXT_CHARS = 200;

/** `product/websites/content_blocks.py::MAX_PARAGRAPH_TEXT_CHARS`. */
export const MAX_PARAGRAPH_TEXT_CHARS = 4000;

/** `product/websites/content_blocks.py::MAX_ALT_TEXT_CHARS`. */
export const MAX_ALT_TEXT_CHARS = 300;

/** `product/websites/content_blocks.py::MAX_ASSET_REF_CHARS`. */
export const MAX_ASSET_REF_CHARS = 512;

/** `product/websites/content_blocks.py::MAX_BUTTON_TEXT_CHARS`. */
export const MAX_BUTTON_TEXT_CHARS = 100;

/** `product/websites/content_blocks.py::MAX_URL_CHARS`. */
export const MAX_URL_CHARS = 2048;

/** `product/websites/content_blocks.py::_validate_heading()` --
 * `block.level` bounds. */
export const MIN_HEADING_LEVEL = 1;
export const MAX_HEADING_LEVEL = 3;
