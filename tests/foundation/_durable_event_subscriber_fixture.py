"""Import-time durable-subscriber registration, used by
tests/foundation/test_events_durable_integration.py's subprocess-
crossing proof. This is deliberately a real, separately-importable
module (never a closure defined inside the test function itself) --
exactly what product/foundation/events.py's own module docstring
requires of a real durable subscriber: registered as a side effect of
importing the module, so a worker process that never ran the test
function still ends up with the same subscription, the same way a real
product module's own subscription would work.

Not a `test_*.py` file -- pytest never collects this as a test module on
its own; it exists only to be imported (by the test, and by the
subprocess the test spawns).
"""

from __future__ import annotations

import os
from pathlib import Path

from product.foundation.events import Event, subscribe_durable

STUB_EVENT_TYPE = "phase2.durable_stub_event"


def _write_marker(event: Event) -> None:
    marker_path = os.environ["DURABLE_EVENT_MARKER_FILE"]
    Path(marker_path).write_text(f"{event.tenant_id}|{event.payload.get('note', '')}")


subscribe_durable(STUB_EVENT_TYPE, _write_marker)
