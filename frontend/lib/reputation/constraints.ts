// Real backend limits, mirrored so the UI can reject an out-of-range
// value immediately instead of waiting on a round-trip 400 -- same
// discipline as `lib/automation/constraints.ts`: validate against the
// backend's own constant, never an arbitrary client-invented cap.

/** `product/reputation/models.py::MAX_AUTHOR_NAME_LENGTH`. */
export const MAX_AUTHOR_NAME_LENGTH = 255;

/** `product/reputation/models.py::MAX_REVIEW_BODY_LENGTH`. */
export const MAX_REVIEW_BODY_LENGTH = 4000;

/** `product/reputation/models.py::MAX_RESPONSE_BODY_LENGTH`. */
export const MAX_RESPONSE_BODY_LENGTH = 4000;

/** `product/reputation/routes.py::CreateReviewRequestRequest.message`
 * -- `Field(max_length=4000)`. */
export const MAX_REQUEST_MESSAGE_LENGTH = 4000;

export const MIN_RATING = 1;
export const MAX_RATING = 5;
