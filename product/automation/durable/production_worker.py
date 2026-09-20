"""The dedicated Phase 10.3 production durable-workflow worker entrypoint
(docs/ROADMAP.md Phase 10.3). A separate process from the Phase 10.3
infrastructure spike's own `worker.py` (which continues to serve only
`ProbeWorkflow` on its own `automation-durable-spike` task queue,
unmodified) -- production runs never share a queue, a worker process, or
a code path with the spike's own probe workflow. Run via `python -m
product.automation.durable.production_worker`, its own Docker Compose
service, independently deployable and independently restartable from
both the API process and the spike's own worker -- identical "separate
process, deliberately" discipline `worker.py`'s own module docstring
already established, restated here for the production task queue.

**Every business activity here is a plain, synchronous `def`**
(`business_activities.py`'s own module docstring) -- this Worker is
therefore built with `activity_executor=` set to a bounded
`ThreadPoolExecutor`, the SDK-documented mechanism for dispatching a
blocking sync activity off the asyncio event loop the Worker's own
poll/dispatch machinery runs on. The spike's own `worker.py` never
needed this (`probe_activity` is `async def`, does no I/O) -- this is a
genuinely new requirement production activities introduce, not an
oversight in the spike.

**Fails clearly, does not retry-loop in Product code** -- identical
reasoning to `worker.py`'s own module docstring, unchanged here.
**Does not block API startup** -- `product/api/main.py` imports
`product.automation.durable.routes` for the API surface, but never this
module; a Temporal outage can make this worker process exit without
affecting the API process at all.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from product.automation.durable.business_activities import ACTIVITIES
from product.automation.durable.config import DurableConfigurationError, get_durable_config
from product.automation.durable.production_workflow import PRODUCTION_TASK_QUEUE, DurableWorkflow

logger = logging.getLogger(__name__)

# Bounded and explicit (mirrors this phase's own "keep retry policy
# bounded and explicit" instruction, applied here to concurrency instead
# of retries) -- each business activity does one bounded, timeout-guarded
# unit of Postgres/CRM/email/webhook work; unbounded thread growth under
# load is not a tradeoff this worker needs to accept for that.
_ACTIVITY_THREAD_POOL_SIZE = 20


async def run_worker() -> None:
    try:
        config = get_durable_config()
    except DurableConfigurationError as exc:
        logger.error("temporal_production_worker_not_configured", extra={"error": str(exc)})
        raise

    logger.info(
        "temporal_production_worker_connecting",
        extra={"target_host": config.target_host, "task_queue": PRODUCTION_TASK_QUEUE},
    )
    try:
        client = await Client.connect(config.target_host, namespace=config.namespace)
    except Exception:
        logger.exception(
            "temporal_production_worker_connection_failed",
            extra={"target_host": config.target_host},
        )
        raise

    logger.info("temporal_production_worker_connected", extra={"task_queue": PRODUCTION_TASK_QUEUE})
    with ThreadPoolExecutor(max_workers=_ACTIVITY_THREAD_POOL_SIZE) as executor:
        worker = Worker(
            client,
            task_queue=PRODUCTION_TASK_QUEUE,
            workflows=[DurableWorkflow],
            activities=ACTIVITIES,
            activity_executor=executor,
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
