"""Configuration for the Phase 10.3 durable-execution infrastructure spike
(package docstring: `product/automation/durable/__init__.py`).

`TEMPORAL_ADDRESS` carries no embedded credential -- a plain `host:port`
pointed at the Temporal server's gRPC frontend, mirroring
`product/api/main.py::_frontend_origins()`'s own `FRONTEND_ORIGINS`
precedent and `infra/jobs/config.py`'s own explicit distinction between
values that can embed credentials (read through `infra.secrets`, e.g.
`REDIS_URL`/`DATABASE_URL`) and plain, non-secret tunables (read directly
from `os.environ`). `infra.secrets` is not used here for exactly that
reason -- not because it would be wrong to, but because there is nothing
secret in a bare `host:port` for local development, and introducing a
second secret-management system for this value is explicitly out of
scope (this phase's own instructions: "do not introduce a second
secret-management system"). A future production deployment adding mTLS
or an API key for a managed Temporal endpoint would extend this module to
read that one additional value through `infra.secrets` -- not build a
parallel mechanism.

**Fails closed, not silently defaulted.** Unlike `REDIS_URL` (required by
SaaS-OS Core at import time, `infra/jobs/config.py`), nothing in this
product imports this module eagerly: `product/api/main.py` never imports
`product.automation.durable` at all (package docstring). `get_durable_config()`
is therefore only ever called by the dedicated worker entrypoint
(`worker.py`) or by a client/test that actually wants to talk to
Temporal -- raising `DurableConfigurationError` here when `TEMPORAL_ADDRESS`
is unset, rather than defaulting to `"localhost:7233"`, never blocks
ordinary API startup and never makes Product usable-without-Temporal
depend on remembering to unset anything. This is the concrete mechanism
behind this phase's own required outcome 14 ("the engine can be disabled
without affecting existing 10.2 single-step automation") and outcome 7
("Product remains usable if Temporal is not configured/started").
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_NAMESPACE = "default"
DEFAULT_TASK_QUEUE = "automation-durable-spike"


class DurableConfigurationError(RuntimeError):
    """`TEMPORAL_ADDRESS` is not set, or another durable-adapter
    configuration value is invalid. Raised only by code that actually
    needs to talk to Temporal (`worker.py`, `client.py`) -- never by
    anything imported at ordinary API startup (module docstring)."""


@dataclass(frozen=True)
class DurableConfig:
    target_host: str
    namespace: str = DEFAULT_NAMESPACE
    task_queue: str = DEFAULT_TASK_QUEUE


def get_durable_config() -> DurableConfig:
    """Reads `TEMPORAL_ADDRESS` (required, e.g. `"temporal:7233"` in
    Docker Compose or `"localhost:7233"` for a bare local dev server),
    `TEMPORAL_NAMESPACE` (optional, default `"default"` -- Temporal's own
    baked-in namespace name), and `TEMPORAL_TASK_QUEUE` (optional, default
    `"automation-durable-spike"`, deliberately spike-specific and never
    reused for a future production task queue name without a conscious
    rename)."""
    target_host = os.environ.get("TEMPORAL_ADDRESS")
    if not target_host:
        raise DurableConfigurationError(
            "TEMPORAL_ADDRESS is not set. Copy .env.example to .env and set a value "
            "(see docker-compose.yml's `temporal` service) -- this is required only by "
            "code that actually talks to the durable-execution engine (the Phase 10.3 "
            "worker entrypoint or a durable-adapter client/test), never by ordinary API "
            "startup or by existing Phase 10.2 single-step automation."
        )
    return DurableConfig(
        target_host=target_host,
        namespace=os.environ.get("TEMPORAL_NAMESPACE", DEFAULT_NAMESPACE),
        task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", DEFAULT_TASK_QUEUE),
    )
