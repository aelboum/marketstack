"""Integration test proving product/foundation/events.py's durable
variant actually survives a process restart -- not merely that the same
process's in-memory subscriber registry happened to still be there
(docs/ROADMAP.md Phase 2.2: "the durable variant survives a simulated
process restart (via infra.jobs)").

Requires a real, reachable Redis (started externally -- see
scripts/check-integration.sh, or `docker compose up -d redis` locally).
Skips (not fails) if Redis is unreachable, mirroring saas-os's own
`_require_reachable_redis` convention exactly.

The proof: the *publishing* process (this test) only ever enqueues --
it never imports the subscriber-registration fixture module before
publishing, and never runs any handler itself. A completely separate
Python subprocess then imports that fixture module (which registers its
handler as an import-time side effect, the only way a durable
subscription is allowed to be declared) and runs a burst worker for
exactly one job. Only if that subprocess's own handler execution left
the marker file behind does this test pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from product.foundation.events import Event, publish_durable

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
async def _require_reachable_redis() -> None:
    try:
        pool = await create_pool(RedisSettings.from_dsn(_REDIS_URL))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"REDIS_URL not configured for the integration test: {exc}")
    try:
        await pool.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"Redis not reachable at the configured REDIS_URL: {exc}. "
            "Run `docker compose up -d redis` first."
        )
    finally:
        await pool.aclose()


_WORKER_SUBPROCESS_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import os

    # Importing this module registers its durable subscriber as an
    # import-time side effect -- this subprocess never ran the test
    # function that called publish_durable(); this import is the ONLY
    # reason it knows about the handler at all.
    import tests.foundation._durable_event_subscriber_fixture  # noqa: F401
    from infra.jobs import build_worker
    from product.foundation.events import DURABLE_EVENT_JOB_FUNCTIONS

    async def main() -> None:
        worker = build_worker(
            DURABLE_EVENT_JOB_FUNCTIONS,
            burst=True,
            queue_name=os.environ["DURABLE_TEST_QUEUE_NAME"],
        )
        try:
            await worker.main()
        finally:
            await worker.close()

    asyncio.run(main())
    """
)


async def test_durable_event_survives_a_simulated_process_restart(tmp_path: Path) -> None:
    from tests.foundation._durable_event_subscriber_fixture import STUB_EVENT_TYPE

    queue_name = f"phase2-durable-events-{uuid.uuid4().hex[:8]}"
    marker_file = tmp_path / "durable_event_marker.txt"
    tenant_id = str(uuid.uuid4())

    event = Event(
        type=STUB_EVENT_TYPE,
        version=1,
        tenant_id=tenant_id,
        payload={"note": "process-boundary-proof"},
    )
    job_id = await publish_durable(event, queue_name=queue_name)
    assert job_id

    assert not marker_file.exists(), "handler must not have run in this process"

    subprocess_env = {
        **os.environ,
        "REDIS_URL": _REDIS_URL,
        "ENVIRONMENT": "test",
        "DURABLE_TEST_QUEUE_NAME": queue_name,
        "DURABLE_EVENT_MARKER_FILE": str(marker_file),
    }
    result = subprocess.run(
        [sys.executable, "-c", _WORKER_SUBPROCESS_SCRIPT],
        cwd=Path(__file__).resolve().parents[2],
        env=subprocess_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"worker subprocess failed:\\nstdout: {result.stdout}\\nstderr: {result.stderr}"
    )

    assert marker_file.exists(), (
        "the worker subprocess never ran the durable handler -- durability claim disproven"
    )
    written = marker_file.read_text()
    assert written == f"{tenant_id}|process-boundary-proof"
