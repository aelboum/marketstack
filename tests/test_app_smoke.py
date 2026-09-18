"""Phase 1 smoke test: the only thing that exists yet is the application
composition root (docs/ROADMAP.md 1.3) -- there is no product logic to
test. This proves product/api/main.py actually builds a working FastAPI
app on top of the installed saas-os package's api.platform
.build_platform_app(), and that the liveness endpoint it mounts responds,
without requiring a real database or Redis (docs/ROADMAP.md 1.3
acceptance criteria: "/health responds correctly").
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from product.api.main import create_app


def test_create_app_builds_and_liveness_endpoint_responds() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
