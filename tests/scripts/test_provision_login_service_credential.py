"""Tests for scripts/provision_login_service_credential.py (docs/ADR/0017)
against an in-memory fake ZITADEL (httpx.MockTransport) -- no real ZITADEL
instance, no real PAT, no real private key material persisted anywhere
but a pytest tmp_path.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from scripts import provision_login_service_credential as mod

_FAKE_PAT = "fake-test-pat-should-never-leak"
_ORG_ID = "org-1"


class FakeZitadel:
    def __init__(self) -> None:
        self.users: list[dict] = []
        self.keys: dict[str, str] = {}
        self.members: dict[str, list[str]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self._next_user_id = 1
        self._next_key_id = 1

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))

        if path == "/management/v1/orgs/me":
            return httpx.Response(200, json={"org": {"id": _ORG_ID}})

        if path == "/v2/users" and request.method == "POST":
            assert body is not None
            queries = {list(q.keys())[0]: list(q.values())[0] for q in body["queries"]}
            username = queries["userNameQuery"]["userName"]
            matches = [u for u in self.users if u["username"] == username]
            return httpx.Response(200, json={"result": matches})

        if path == "/v2/users/new":
            assert body is not None
            user_id = f"user-{self._next_user_id}"
            self._next_user_id += 1
            self.users.append({"userId": user_id, "username": body["username"]})
            return httpx.Response(200, json={"id": user_id})

        if path.endswith("/keys") and request.method == "POST":
            assert body is not None
            key_id = f"key-{self._next_key_id}"
            self._next_key_id += 1
            user_id = path.split("/")[2]
            self.keys[key_id] = body["publicKey"]
            return httpx.Response(200, json={"keyId": key_id, "userId": user_id})

        if path == "/admin/v1/members":
            assert body is not None
            self.members.setdefault(body["userId"], []).extend(body["roles"])
            return httpx.Response(200, json={})

        raise AssertionError(f"unexpected request: {request.method} {path}")


@pytest.fixture
def env(monkeypatch, tmp_path):
    pat_path = tmp_path / "bootstrap.pat"
    pat_path.write_text(_FAKE_PAT, encoding="utf-8")
    monkeypatch.setenv("ZITADEL_INTERNAL_URL", "http://zitadel.test")
    monkeypatch.setenv("ZITADEL_BOOTSTRAP_PAT_PATH", str(pat_path))
    monkeypatch.setenv("OIDC_LOCAL_PROJECT_NAME", "product")
    monkeypatch.setenv("LOGIN_SERVICE_ZITADEL_USERNAME", "login-service")
    return tmp_path


def _provision(fake: FakeZitadel, output_dir: str) -> None:
    mod.provision(output_dir=output_dir, transport=fake.transport())


def test_first_run_creates_user_key_and_role_grant(env):
    fake = FakeZitadel()
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    assert len(fake.users) == 1
    assert fake.users[0]["username"] == "login-service"
    assert len(fake.keys) == 1
    user_id = fake.users[0]["userId"]
    assert fake.members[user_id] == ["IAM_LOGIN_CLIENT"]


def test_first_run_writes_expected_output_files(env):
    fake = FakeZitadel()
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    import os

    assert os.path.exists(os.path.join(output_dir, "private_key.pem"))
    assert os.path.exists(os.path.join(output_dir, "service_user_id.txt"))
    assert os.path.exists(os.path.join(output_dir, "key_id.txt"))
    with open(os.path.join(output_dir, "private_key.pem"), encoding="utf-8") as f:
        assert "BEGIN PRIVATE KEY" in f.read()


def test_second_run_is_a_no_op(env):
    fake = FakeZitadel()
    output_dir = str(env / "cred")

    _provision(fake, output_dir)
    calls_after_first_run = len(fake.calls)

    _provision(fake, output_dir)

    assert len(fake.calls) == calls_after_first_run
    assert len(fake.users) == 1


def test_public_key_sent_never_the_private_key(env):
    fake = FakeZitadel()
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    sent_public_key = base64.b64decode(next(iter(fake.keys.values())))
    assert b"BEGIN PUBLIC KEY" in sent_public_key
    assert b"BEGIN PRIVATE KEY" not in sent_public_key


def test_reuses_existing_user_if_already_present(env):
    fake = FakeZitadel()
    fake.users.append({"userId": "existing-user", "username": "login-service"})
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    assert len(fake.users) == 1  # no second user created
    assert "existing-user" in fake.members


def test_credential_error_never_carries_pat():
    error = mod.ProvisioningError("some failure")
    assert _FAKE_PAT not in str(error)
