"""Test bootstrap: sets required env vars (mirrors the main product's own
root `conftest.py`, which does the same for `product.api.main`) and writes
a throwaway RSA private key for `app.main` to load at import time, BEFORE
any test imports `app.main`.

No real ZITADEL instance, no real credential -- `tests/fakes.py` provides
an in-memory `FakeZitadelClient` swapped in for `app.main.zitadel` (see
`app_client` fixture below).
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY_PATH = os.path.join(os.path.dirname(__file__), "_test_private_key.pem")


def _write_test_private_key() -> None:
    if os.path.exists(_KEY_PATH):
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(_KEY_PATH, "wb") as f:
        f.write(pem)


_write_test_private_key()

os.environ.setdefault("ZITADEL_ISSUER_URL", "http://zitadel.test")
os.environ.setdefault("LOGIN_SERVICE_ZITADEL_USER_ID", "test-service-user-id")
os.environ.setdefault("LOGIN_SERVICE_ZITADEL_KEY_ID", "test-key-id")
os.environ.setdefault("LOGIN_SERVICE_PRIVATE_KEY_PATH", _KEY_PATH)
os.environ.setdefault("LOGIN_SERVICE_PUBLIC_ORIGIN", "http://localhost:8080")
os.environ.setdefault("LOGIN_SERVICE_COOKIE_SECURE", "false")
os.environ.setdefault("LOGIN_SERVICE_BRAND_NAME", "Test Product")

import pytest  # noqa: E402 -- must follow the env setup above
from app import main as login_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tests.fakes import FakeZitadel  # noqa: E402


@pytest.fixture
def fake_zitadel() -> FakeZitadel:
    return FakeZitadel()


@pytest.fixture
def client(fake_zitadel: FakeZitadel, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(login_app, "zitadel", fake_zitadel)
    return TestClient(login_app.app)
