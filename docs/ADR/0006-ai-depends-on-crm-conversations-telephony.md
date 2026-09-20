# ADR-0006: AI May Depend on CRM, Conversations, and Telephony (One-Directional)

Status: ACCEPTED
Date: 2026-09-20

## Context

`docs/ROADMAP.md` Phase 9.1's own Objective is "register `control_plane`
tools for lead qualification, suggested next actions, and conversation
summarization" — every one of these needs a live, current read of another
product module's own tenant-owned data (a CRM contact/opportunity, a
Conversations thread's messages) before the tool's handler can hand
anything to an LLM provider. Phase 9.3 adds a fourth tool
(suggested-reply drafting) with the identical Conversations dependency.
Phase 9.2 (AI receptionist) needs a read of the Telephony call it is
advising on.

This is the same situation `docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`
already resolved for Marketing and Appointments, applied to a third
module (`product.ai`) with a wider — but still narrow, still
one-directional, still read-only — set of dependency edges: CRM,
Conversations, and Telephony, never each other through `product.ai` as
an intermediary, and never the reverse direction into `product.ai`.

`docs/ARCHITECTURE.md` §2.2's two sanctioned paths (promote to
`product/foundation/`, or react via the event dispatcher) fit this no
better than they fit ADR-0005's own case: a tool invocation needs the
*current* contact/thread/call state at the moment an agent asks a
question, not a foundation-level generic capability or a replayed event
stream.

## Decision

1. `product.ai` MAY import `product.crm`'s, `product.conversations`'s,
   and `product.telephony`'s own published, read-oriented service
   functions (`product.crm.contacts.get_contact()`,
   `product.crm.opportunities.get_opportunity()`,
   `product.conversations.messages.list_messages()`,
   `product.conversations.threads.get_thread()`,
   `product.telephony.calls.get_call()`) — never any of their `.models`
   modules directly, and never any other product module's internals.
   None of `product.crm`/`product.conversations`/`product.telephony` may
   ever import `product.ai` — every edge is one-directional, matching the
   actual data-flow direction (a tool *reads* another module's data to
   answer a question; nothing downstream of `product.ai` exists yet for
   any of those three modules to legitimately need back).
2. Every one of these reads happens **inside a registered
   `control_plane.orchestration.ToolDefinition`'s own handler**, which
   already re-authorizes the read via that module's own
   `actor_user_id`/`tenant_id`-scoped `core.rbac.can()` check (e.g.
   `crm.contacts.get_contact()` calls `product.crm.permissions.require()`
   itself) — `product.ai` never bypasses the target module's own
   authorization by reaching into its tables directly. This is
   defense-in-depth, not a new authorization path: the tool's own
   `ToolDefinition.required_resource`/`required_action` (deliberately set
   to the *same* resource the underlying module already gates — e.g.
   `crm.contact`/`read` for the lead-qualification tool) is checked first
   by `control_plane.orchestration.service._is_authorized()`, then the
   handler's own call into `product.crm.contacts.get_contact()` checks it
   again independently. An invoking agent that could not already read the
   contact/thread/call directly cannot read it via an AI tool either.
3. `product.ai` remains fully independent from every other product module
   (`agency`, `marketing`, `appointments`, `automation`, `reputation`,
   `websites`, `billing`, `accounting`, `reporting`, `white_label`,
   `templates`, `integrations`) — this exception is narrow and specific
   to the three modules named above, not a general loosening of §2.2's
   rule for every module pair, and not a license for
   CRM/Conversations/Telephony to depend on each other through
   `product.ai`. Any future module needing a similar exception requires
   its own, separately-justified ADR — this decision does not
   pre-authorize it.
4. Enforced by `pyproject.toml`'s `[tool.importlinter]` configuration:
   - `"product.ai"` is removed from the existing "Product modules do not
     depend on each other directly" independence contract's `modules`
     list — it now has its own, more precise rule instead of the blanket
     one.
   - A new `forbidden`-type contract, `"AI does not depend on any product
     module except CRM, Conversations, or Telephony"`
     (`source_modules = ["product.ai"]`, `forbidden_modules` = every
     product module except those three), mirrors the exact shape of the
     existing Marketing/Appointments contract.
   - Three separate `layers`-type contracts — `product.ai` -> `product.crm`,
     `product.ai` -> `product.conversations`, `product.ai` -> `product.telephony`
     — never one multi-layer contract folding all three into a single
     shared layer (that shape would also permit
     `product.crm` <-> `product.conversations` <-> `product.telephony`
     through `product.ai` as an intermediary, which is not part of this
     decision, mirroring ADR-0005's own identical reasoning for why
     Marketing and Appointments each got their own separate layers
     contract rather than one shared one).

## Consequences

- `product/ai/tools/*.py` each import exactly one of
  `product.crm`/`product.conversations`/`product.telephony`'s own
  published functions, never more than the one dependency that specific
  tool actually needs.
- `product.ai` still never imports `product.agency` — permission-granting
  for `product.ai`'s own resources (there are none; every tool reuses an
  existing CRM/Conversations/Telephony resource, per this ADR's own point
  2) follows the same event-dispatcher path every other module uses,
  the day `product.ai` ever needs one of its own.
- A future Phase 9 subphase needing a read from a *fourth* product module
  (e.g. Marketing, for a future marketing-assistant tool) requires
  extending this ADR explicitly, not assuming the pattern established
  here already covers it.

## Rejected Alternative

Duplicating a read-only projection of CRM contacts/Conversations messages/
Telephony calls inside `product.ai` (e.g. via the event dispatcher,
replaying `agency.role_provisioned`-style events into a local cache) was
considered and rejected for the identical reason ADR-0005 already
rejected it for Marketing: no such event stream exists for any of these
three modules' own entity mutations today (Phase 4 only ever published
`crm.opportunity.stage_changed`), and building one now, for every module
an AI tool might ever need to read, is new infrastructure the roadmap
does not ask for ("almost entirely about registering this product's own
tools, never about building agent infrastructure" — Phase 9's own
opening line) to serve a need a direct, re-authorized read already
satisfies correctly.
