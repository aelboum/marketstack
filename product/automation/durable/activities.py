"""The one trivial activity this infrastructure spike defines (package
docstring: `product/automation/durable/__init__.py`'s "Activity security
boundary" section).

**No business side effect, by design.** This activity does not send
email, does not send a webhook, does not mutate CRM, does not create an
appointment, does not touch telephony, does not invoke AI, does not
access an arbitrary URL or database, and does not execute arbitrary code
or accept an arbitrary Python callable -- it exists solely to prove that
Temporal can schedule and execute *some* unit of work reliably, survive a
worker restart while doing so, and keep the result bounded and
deterministic. It takes no database connection, makes no `core.rbac`/
`core.audit_log` call, and reads no secret -- there is nothing here to
authorize, so nothing here re-enters the Product authorization boundary.

**A future production activity is different in exactly one way**: it
calls `product.automation.actions.execute_action(...)` (or an equivalent
already-RBAC-gated Product function) instead of this file's own inert
string transform, so that every real side effect still goes through
`core.rbac.can()`/`require()` at the moment it actually executes -- see
the package docstring's "Activity security boundary" section. Nothing in
`activities.py` needs to change shape for that to happen: the activity
function signature (bounded, typed input in, bounded, typed output out)
is already the right shape for that future call.

**Bounded input/output, by construction**: `ProbeActivityInput` carries
only two plain strings (`tenant_id`, `resource_id`), both length-capped
at construction (`_MAX_FIELD_LENGTH`) -- never an arbitrary-size payload,
never a nested/user-controlled structure, mirroring
`product/automation/models.py`'s own "bounded JSON, never unbounded
blobs" discipline for the eventual production workflow's own step
arguments.
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import activity

_MAX_FIELD_LENGTH = 255


class ProbeActivityInputError(ValueError):
    """`tenant_id`/`resource_id` failed the bounded-input check below."""


@dataclass(frozen=True, slots=True)
class ProbeActivityInput:
    tenant_id: str
    resource_id: str

    def __post_init__(self) -> None:
        for field_name, value in (("tenant_id", self.tenant_id), ("resource_id", self.resource_id)):
            if not value or len(value) > _MAX_FIELD_LENGTH:
                raise ProbeActivityInputError(
                    f"{field_name} must be a non-empty string of at most "
                    f"{_MAX_FIELD_LENGTH} characters, got length {len(value)}."
                )


@dataclass(frozen=True, slots=True)
class ProbeActivityOutput:
    echoed_tenant_id: str
    echoed_resource_id: str


@activity.defn
async def probe_activity(input: ProbeActivityInput) -> ProbeActivityOutput:
    """Pure, deterministic, no I/O: echoes its own bounded input back.
    No database session, no network call, no filesystem access, no
    `core.rbac`/`core.audit_log` call -- see module docstring. Callable
    directly (outside any Temporal worker/activity-execution context,
    e.g. `asyncio.run(probe_activity(...))`) precisely because it makes
    no call into the SDK's own execution-context accessors
    (`temporalio.activity.info()` and similar), which require a real
    activity context and would otherwise make this function untestable
    in isolation."""
    return ProbeActivityOutput(
        echoed_tenant_id=input.tenant_id,
        echoed_resource_id=input.resource_id,
    )
