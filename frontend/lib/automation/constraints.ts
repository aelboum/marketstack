// Real backend limits, mirrored so the UI can reject an out-of-range
// value immediately instead of waiting on a round-trip 400 -- the UI-3
// lesson: validate against the backend's own constant, never an
// arbitrary client-invented cap.

/** `product/automation/durable/routes.py::CreateWorkflowRequest.name`
 * -- `Field(max_length=255)`. */
export const MAX_WORKFLOW_NAME_LENGTH = 255;

/** `product/automation/durable/dsl.py::MAX_STEPS`. Not enforceable
 * against anything this UI builds (it only ever writes one step), but
 * recorded here since it is the real ceiling a richer step graph built
 * outside this UI could reach. */
export const MAX_STEPS = 20;

/** `product/automation/conditions.py::MAX_CONDITIONS`. Same note --
 * this UI never writes a condition step. */
export const MAX_CONDITIONS = 10;
