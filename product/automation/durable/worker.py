"""The dedicated Phase 10.3 Temporal worker entrypoint (package docstring:
`product/automation/durable/__init__.py`).

**A separate process, deliberately.** Not merged into FastAPI startup,
not merged into a (currently nonexistent -- this product has never
registered an `infra.jobs`/ARQ background job or stood up an ARQ worker
process/service; verified by inspecting `docker-compose.yml` and
`product/api/` directly, not assumed) ARQ worker, and not merged into the
API process. Run via `python -m product.automation.durable.worker`, as
its own Docker Compose service (`temporal-worker`, `docker-compose.yml`)
-- the API and this worker remain independently deployable and
independently restartable, exactly this phase's own required outcome 7
("Product API and worker remain separate processes").

**Fails clearly, does not retry-loop in Product code.** `Client.connect()`
raises on an unreachable Temporal endpoint; this entrypoint lets that
propagate as a non-zero exit with the real error printed, rather than
wrapping it in a bespoke reconnect/backoff loop -- Temporal's own worker
(`temporalio.worker.Worker`) already handles ordinary poll-connection
recovery once started (this phase's own instructions: "do not implement a
complicated retry framework in Product code"). A container orchestrator
(Docker Compose's own `restart` policy, or a production equivalent)
is the intended layer for "the process exited, start it again" --
not this module.

**Does not block API startup.** `product/api/main.py` never imports this
module (package docstring) -- a Temporal outage can make *this* process
exit, and cannot make the API process fail to start or fail to serve any
existing route, including every existing Phase 10.2 automation endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from product.automation.durable.activities import probe_activity
from product.automation.durable.config import DurableConfigurationError, get_durable_config
from product.automation.durable.workflows import ProbeWorkflow

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    try:
        config = get_durable_config()
    except DurableConfigurationError as exc:
        logger.error("temporal_worker_not_configured", extra={"error": str(exc)})
        raise

    logger.info(
        "temporal_worker_connecting",
        extra={"target_host": config.target_host, "task_queue": config.task_queue},
    )
    try:
        client = await Client.connect(config.target_host, namespace=config.namespace)
    except Exception:
        logger.exception(
            "temporal_worker_connection_failed", extra={"target_host": config.target_host}
        )
        raise

    logger.info("temporal_worker_connected", extra={"task_queue": config.task_queue})
    worker = Worker(
        client,
        task_queue=config.task_queue,
        workflows=[ProbeWorkflow],
        activities=[probe_activity],
    )
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
