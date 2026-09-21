// Human-facing metadata for the five action types UI-10 builds forms
// for, and the trigger types the durable dispatcher matches. Kept
// separate from `lib/api/automation.ts` so that file stays a pure wire
// client -- this is presentation-layer labeling only, not part of the
// contract.
import type { ActionType, TriggerType } from "@/lib/api/automation";

export const ACTION_LABELS: Record<ActionType, string> = {
  create_task: "Create a task",
  update_contact: "Update the contact",
  move_opportunity: "Move the opportunity's stage",
  send_email: "Send an email",
  send_webhook: "Send a webhook",
};

/** `update_contact` and `move_opportunity` both act on an id
 * (`contact_id`/`opportunity_id`) the backend reads out of the
 * *triggering event's own payload* -- never out of `action_config`
 * (`product/automation/actions.py::_extract_trigger_ids()`). Shown next
 * to those two forms so the "why is there no contact/opportunity field
 * here" question has a real answer instead of an apparent omission. */
export const ACTION_TRIGGER_ID_NOTE: Partial<Record<ActionType, string>> = {
  update_contact:
    "Applies to the contact from the event that triggered this run -- there is no contact field to fill in here.",
  move_opportunity:
    "Applies to the opportunity from the event that triggered this run -- there is no opportunity field to fill in here.",
};

export const TRIGGER_LABELS: Record<TriggerType, string> = {
  "crm.contact.created": "A contact is created",
  "appointments.appointment.booked": "An appointment is booked",
  "telephony.call.completed": "A call completes",
  "crm.opportunity.stage_changed": "An opportunity changes stage",
};
