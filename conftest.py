"""Root pytest configuration -- hermetic default suite, mirroring saas-os's
own root conftest.py pattern exactly (same underlying cause: `core.identity
.session_retention` and other Core modules register background-job handlers
at *import* time via `infra.jobs.register_job()`, which resolves
`REDIS_URL` through the active `SecretsProvider` right then; `infra.secrets`
also requires `ENVIRONMENT` to be set explicitly, with no permissive
default). Without this, `import product.api.main` (which imports
`api.platform`, which imports `core.rbac`, ...) fails at collection in any
environment with no `.env` -- exactly what this repository's own CI is.

`os.environ.setdefault` only ever fills a genuinely absent value -- an
explicitly exported `ENVIRONMENT`/`REDIS_URL` (a developer's shell, CI, or
a real deployment's `.env`/compose file) always wins.
"""

from __future__ import annotations

import os

_HERMETIC_REDIS_URL = "redis://127.0.0.1:6379/0"

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", _HERMETIC_REDIS_URL)
