"""Unit tests for product/foundation/events.py's in-process, synchronous
variant only. No database, no Redis -- see
tests/foundation/test_events_durable_integration.py for the
infra.jobs-backed durable variant, which does need a real disposable
Redis and is marked `integration`.
"""

from __future__ import annotations

from product.foundation import events
from product.foundation.events import Event


def _fresh_registry() -> None:
    events._SUBSCRIBERS.clear()  # noqa: SLF001 -- test-only reset of module state


def test_publish_calls_subscribed_handler() -> None:
    _fresh_registry()
    received: list[Event] = []
    events.subscribe("stub.event", received.append)

    event = Event(type="stub.event", version=1, tenant_id="tenant-a", payload={"x": 1})
    events.publish(event)

    assert received == [event]


def test_publish_calls_handlers_in_registration_order() -> None:
    _fresh_registry()
    order: list[str] = []
    events.subscribe("stub.event", lambda e: order.append("first"))
    events.subscribe("stub.event", lambda e: order.append("second"))

    events.publish(Event(type="stub.event", version=1, tenant_id="t", payload={}))

    assert order == ["first", "second"]


def test_adversarial_wrong_event_type_never_invoked() -> None:
    """Security requirement (docs/ROADMAP.md Phase 2.2): a handler
    subscribed to one event type must never be invoked for a different
    event type -- the dispatcher routes by exact type match only, never
    a broadcast."""
    _fresh_registry()
    wrong_type_calls: list[Event] = []
    right_type_calls: list[Event] = []
    events.subscribe("type.a", wrong_type_calls.append)
    events.subscribe("type.b", right_type_calls.append)

    events.publish(Event(type="type.b", version=1, tenant_id="tenant-x", payload={}))

    assert wrong_type_calls == []
    assert len(right_type_calls) == 1
    assert right_type_calls[0].tenant_id == "tenant-x"


def test_adversarial_tenant_id_reaches_handler_unmodified() -> None:
    """A handler must receive exactly the tenant_id the event was
    published with -- the dispatcher never substitutes, widens, or
    drops it."""
    _fresh_registry()
    received: list[Event] = []
    events.subscribe("tenant.check", received.append)

    events.publish(
        Event(type="tenant.check", version=1, tenant_id="tenant-only-this-one", payload={})
    )

    assert len(received) == 1
    assert received[0].tenant_id == "tenant-only-this-one"


def test_publish_with_no_subscribers_is_a_silent_no_op() -> None:
    _fresh_registry()
    # Must not raise for an event type nobody subscribed to.
    events.publish(Event(type="nobody.listens", version=1, tenant_id="t", payload={}))


def test_event_is_frozen() -> None:
    event = Event(type="x", version=1, tenant_id="t", payload={})
    try:
        event.type = "y"  # type: ignore[misc]
        raised = False
    except AttributeError:
        raised = True
    assert raised, "Event must be a frozen dataclass"
