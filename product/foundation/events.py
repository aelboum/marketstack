"""The product event dispatcher (docs/ROADMAP.md Phase 2.2;
docs/ARCHITECTURE.md section 4).

Category B (interim): SaaS-OS documents event *ownership* rules
(docs/DATA-ARCHITECTURE.md section 4 there) but ships no in-process
transport -- `core/webhooks` is outbound HTTP delivery to *external*
subscribers, not an internal module-to-module bus. This is built here,
product-side, narrow enough (`publish`/`subscribe`, `publish_durable`/
`subscribe_durable`) to be re-pointed at a future SaaS-OS-provided
implementation without a call-site rewrite, should a second product on
SaaS-OS ever need the same thing (docs/ARCHITECTURE.md section 4's own
stated future path).

No module publishes a real event yet (docs/ROADMAP.md Phase 2.2: "this
phase proves the mechanism with a stub event"). The first real event
(`crm.opportunity.stage_changed`, Phase 4.2) is not built here.

**Two variants, two different durability guarantees -- do not confuse
their subscriber registries:**

- `subscribe()`/`publish()`: synchronous, in-process only. A handler
  registered via `subscribe()` exists only in the calling process's own
  memory -- fine for same-request reactions, gone the instant that
  process exits or restarts.
- `subscribe_durable()`/`publish_durable()`: `publish_durable()` only
  enqueues (via `infra.jobs.enqueue_job`) -- delivery happens later, in
  whatever process runs the worker (`infra.jobs.build_worker()` over
  `DURABLE_EVENT_JOB_FUNCTIONS`), which may not be the process that
  published the event and may not even exist yet at publish time. For
  that worker process to know which handlers to call, every durable
  subscription MUST be registered by a module-level `subscribe_durable()`
  call (executed at import time, as a side effect of importing that
  module -- not inside a function body, and never inside a test's local
  closure) so any process that imports the product's modules ends up
  with the same `DURABLE_SUBSCRIBERS` registry, including a freshly
  started worker process that never ran the code that originally
  published the event.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from infra.jobs import TenantJobPayload, enqueue_job, register_job

EventHandler = Callable[["Event"], None]


@dataclass(frozen=True, slots=True)
class Event:
    """A single product domain event. `version` is part of this event
    `type`'s own schema contract (docs/ARCHITECTURE.md section 4: "every
    event schema is versioned from its first definition") -- a later,
    incompatible change to what `payload` contains for a given `type`
    bumps `version`, it never silently changes shape under subscribers'
    feet. `tenant_id` is a `str` (not `uuid.UUID`) to match
    `infra.jobs.TenantJobPayload.tenant_id`'s own type exactly, since
    every durable event round-trips through one.

    NOTE on immutability: `frozen=True` prevents reassigning this
    dataclass's own fields (`event.type = "x"` raises), but `payload`'s
    *contents* are an ordinary mutable `dict` -- frozen dataclasses do
    not reach inside a mutable field. A subscriber handler must treat
    `payload` as read-only by convention; this module does not (and
    cannot, without a deep-freeze) enforce that for you.
    """

    type: str
    version: int
    tenant_id: str
    payload: dict[str, object] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# --- In-process, synchronous variant ---------------------------------------

_SUBSCRIBERS: dict[str, list[EventHandler]] = {}


def subscribe(event_type: str, handler: EventHandler) -> None:
    """Register `handler` to be called, synchronously, every time
    `publish()` is called with an `Event` of this exact `event_type`."""
    _SUBSCRIBERS.setdefault(event_type, []).append(handler)


def publish(event: Event) -> None:
    """Call every handler subscribed to `event.type`, synchronously, in
    registration order. A handler subscribed to a *different*
    `event_type` is never called -- routing is by exact `event.type`
    match only, never a broadcast. Iterates a copy of the subscriber
    list so a handler that itself calls `subscribe()` mid-dispatch never
    mutates the list being iterated."""
    for handler in list(_SUBSCRIBERS.get(event.type, [])):
        handler(event)


# --- Durable variant, backed by infra.jobs ----------------------------------

DURABLE_SUBSCRIBERS: dict[str, list[EventHandler]] = {}


def subscribe_durable(event_type: str, handler: EventHandler) -> None:
    """Register `handler` in the *durable* subscriber registry. Call
    this only at module import time (see module docstring) -- a handler
    registered any other way will not be visible to a worker process
    that did not happen to run the same code path."""
    DURABLE_SUBSCRIBERS.setdefault(event_type, []).append(handler)


async def _dispatch_durable_event_job(payload: TenantJobPayload | None) -> None:
    """The registered arq job handler (mirrors
    `core.notifications.service._dispatch_notification_job`'s own shape
    exactly). Reconstructs the `Event` from the job payload and calls
    every handler currently registered in `DURABLE_SUBSCRIBERS` for its
    `type`, in whatever process this worker is running in -- which is
    the entire point: that registry is populated by ordinary module
    imports, not by anything carried over from the publishing process's
    memory.
    """
    if payload is None:
        raise ValueError("_dispatch_durable_event_job requires a TenantJobPayload, got None.")

    data = payload.data
    event = Event(
        type=str(data["type"]),
        version=int(data["version"]),
        tenant_id=payload.tenant_id,
        payload=dict(data["payload"]),
        occurred_at=datetime.fromisoformat(str(data["occurred_at"])),
    )
    for handler in list(DURABLE_SUBSCRIBERS.get(event.type, [])):
        handler(event)


# Exported the same way `core.notifications.NOTIFICATION_JOB_FUNCTIONS` is,
# for a worker process to register (docs/ROADMAP.md Phase 10 is the first
# phase that actually stands up a worker process/service -- not built here;
# this list exists so that later phase's worker has something real to
# import, and so this phase's own durability test can build a worker
# without inventing a second registration mechanism).
DURABLE_EVENT_JOB_FUNCTIONS = [register_job(_dispatch_durable_event_job)]


async def publish_durable(event: Event, *, queue_name: str | None = None) -> str:
    """Enqueue `event` for durable, at-least-once delivery. Returns the
    arq job id. This call only enqueues -- it does not run any handler
    itself, and does not guarantee delivery has happened by the time it
    returns (docs/ARCHITECTURE.md section 4: an `infra.jobs`-backed
    variant, for reactions that must survive a process restart)."""
    payload = TenantJobPayload(
        tenant_id=event.tenant_id,
        data={
            "type": event.type,
            "version": event.version,
            "payload": event.payload,
            "occurred_at": event.occurred_at.isoformat(),
        },
    )
    return await enqueue_job(
        _dispatch_durable_event_job.__name__,
        payload,
        queue_name=queue_name,
    )
