"""Tests for scripts/provision_login_service_credential.py (docs/ADR/0017)
against an in-memory fake ZITADEL (httpx.MockTransport) -- no real ZITADEL
instance, no real PAT, no real private key material persisted anywhere
but a pytest tmp_path.

F-01/F-02 (Login Service security audit) coverage: key-reconciliation
(no accumulation, obsolete-only, unrelated-user keys preserved) and
fail-closed IAM role-grant handling (409 idempotent, everything else
aborts before any key or credential file exists).
"""

from __future__ import annotations

import base64
import json
import os

import httpx
import pytest

from scripts import provision_login_service_credential as mod

_FAKE_PAT = "fake-test-pat-should-never-leak"
_ORG_ID = "org-1"


class FakeZitadel:
    def __init__(self) -> None:
        self.users: list[dict] = []
        self.keys: dict[str, dict] = {}  # key_id -> {"user_id": ..., "public_key_b64": ...}
        self.members: dict[str, list[str]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self._next_user_id = 1
        self._next_key_id = 1
        # None -> AddIAMMember succeeds normally. Set to e.g. 409 or 403 to
        # simulate that response instead (F-02 tests).
        self.member_grant_status: int | None = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        method = request.method
        self.calls.append((method, path, body))

        if path == "/management/v1/orgs/me":
            return httpx.Response(200, json={"org": {"id": _ORG_ID}})

        if path == "/v2/users" and method == "POST":
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

        if path.endswith("/keys") and method == "POST":
            assert body is not None
            key_id = f"key-{self._next_key_id}"
            self._next_key_id += 1
            user_id = path.split("/")[2]
            self.keys[key_id] = {"user_id": user_id, "public_key_b64": body["publicKey"]}
            return httpx.Response(200, json={"keyId": key_id, "userId": user_id})

        if path == "/v2/users/keys/search" and method == "POST":
            assert body is not None
            filters = body.get("filters", [])
            user_id_filter = next(
                (f["userIdFilter"]["id"] for f in filters if "userIdFilter" in f), None
            )
            result = [
                {"id": key_id, "userId": info["user_id"]}
                for key_id, info in self.keys.items()
                if user_id_filter is None or info["user_id"] == user_id_filter
            ]
            return httpx.Response(200, json={"result": result})

        if method == "DELETE" and "/keys/" in path:
            key_id = path.rsplit("/", 1)[-1]
            self.keys.pop(key_id, None)
            return httpx.Response(200, json={})

        if path == "/admin/v1/members":
            assert body is not None
            if self.member_grant_status is not None:
                return httpx.Response(
                    self.member_grant_status,
                    json={"code": 7, "message": "simulated failure"},
                )
            self.members.setdefault(body["userId"], []).extend(body["roles"])
            return httpx.Response(200, json={})

        raise AssertionError(f"unexpected request: {method} {path}")


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


def _output_files_exist(output_dir: str) -> bool:
    return all(
        os.path.exists(os.path.join(output_dir, name))
        for name in ("private_key.pem", "service_user_id.txt", "key_id.txt")
    )


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

    assert _output_files_exist(output_dir)
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
    assert len(fake.keys) == 1  # scenario B: no unnecessary additional key


def test_public_key_sent_never_the_private_key(env):
    fake = FakeZitadel()
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    sent_public_key = base64.b64decode(next(iter(fake.keys.values()))["public_key_b64"])
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


# --- F-01: key reconciliation ------------------------------------------------


def test_scenario_c_reconciles_obsolete_key_after_local_credential_lost(env):
    """Local files absent but the machine user + a previously-issued key
    already exist server-side (e.g. the credential volume was recreated).
    The obsolete key must be removed only after its replacement exists,
    leaving exactly one active key -- no accumulation."""
    fake = FakeZitadel()
    fake.users.append({"userId": "existing-user", "username": "login-service"})
    fake.keys["stale-key"] = {"user_id": "existing-user", "public_key_b64": "b3Zh"}
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    assert "stale-key" not in fake.keys
    assert len(fake.keys) == 1
    new_key_id = next(iter(fake.keys))
    with open(os.path.join(output_dir, "key_id.txt"), encoding="utf-8") as f:
        assert f.read() == new_key_id


def test_multiple_previously_orphaned_keys_are_all_reconciled_to_one(env):
    """Simulates the exact live-observed F-01 failure (repeated
    provisioning runs before this fix accumulated 3 keys on one user)."""
    fake = FakeZitadel()
    fake.users.append({"userId": "existing-user", "username": "login-service"})
    fake.keys["orphan-1"] = {"user_id": "existing-user", "public_key_b64": "b3Zh"}
    fake.keys["orphan-2"] = {"user_id": "existing-user", "public_key_b64": "b3Zh"}
    fake.keys["orphan-3"] = {"user_id": "existing-user", "public_key_b64": "b3Zh"}
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    assert len(fake.keys) == 1
    assert "orphan-1" not in fake.keys
    assert "orphan-2" not in fake.keys
    assert "orphan-3" not in fake.keys


def test_obsolete_keys_removed_only_after_replacement_exists(env, monkeypatch):
    """Order-of-operations proof: at the moment AddKey is called, the
    obsolete key must still exist (not deleted preemptively)."""
    fake = FakeZitadel()
    fake.users.append({"userId": "existing-user", "username": "login-service"})
    fake.keys["stale-key"] = {"user_id": "existing-user", "public_key_b64": "b3Zh"}
    output_dir = str(env / "cred")

    original_add_key = mod.add_key
    stale_key_present_during_add_key = {}

    def spying_add_key(client, **kwargs):
        stale_key_present_during_add_key["value"] = "stale-key" in fake.keys
        return original_add_key(client, **kwargs)

    monkeypatch.setattr(mod, "add_key", spying_add_key)

    _provision(fake, output_dir)

    assert stale_key_present_during_add_key["value"] is True
    assert "stale-key" not in fake.keys  # removed afterward


def test_unrelated_machine_user_keys_are_preserved(env):
    """Scenario F: a key belonging to a different machine user must never
    be listed or touched by this dedicated user's reconciliation."""
    fake = FakeZitadel()
    fake.users.append({"userId": "existing-user", "username": "login-service"})
    fake.keys["stale-key"] = {"user_id": "existing-user", "public_key_b64": "b3Zh"}
    fake.keys["unrelated-key"] = {"user_id": "some-other-user", "public_key_b64": "eA=="}
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    assert "unrelated-key" in fake.keys
    assert fake.keys["unrelated-key"]["user_id"] == "some-other-user"


def test_no_unnecessary_key_created_when_already_provisioned(env):
    """Scenario B, restated explicitly for F-01: re-running with the local
    credential files intact must not touch ZITADEL at all."""
    fake = FakeZitadel()
    output_dir = str(env / "cred")
    _provision(fake, output_dir)
    assert len(fake.keys) == 1

    _provision(fake, output_dir)

    assert len(fake.keys) == 1


# --- F-02: fail-closed IAM role grant -----------------------------------------


def test_already_member_409_is_idempotent_and_still_succeeds(env):
    fake = FakeZitadel()
    fake.member_grant_status = 409
    output_dir = str(env / "cred")

    _provision(fake, output_dir)

    assert _output_files_exist(output_dir)
    assert len(fake.keys) == 1


def test_unexpected_member_grant_failure_aborts_provisioning(env):
    fake = FakeZitadel()
    fake.member_grant_status = 403
    output_dir = str(env / "cred")

    with pytest.raises(mod.ProvisioningError):
        _provision(fake, output_dir)


def test_credential_files_not_published_after_iam_grant_failure(env):
    fake = FakeZitadel()
    fake.member_grant_status = 403
    output_dir = str(env / "cred")

    with pytest.raises(mod.ProvisioningError):
        _provision(fake, output_dir)

    assert not _output_files_exist(output_dir)


def test_no_key_created_when_iam_grant_fails(env):
    """The whole point of F-02's reordering: authorization must be
    confirmed BEFORE a key ever exists."""
    fake = FakeZitadel()
    fake.member_grant_status = 403
    output_dir = str(env / "cred")

    with pytest.raises(mod.ProvisioningError):
        _provision(fake, output_dir)

    assert fake.keys == {}


def test_iam_grant_failure_message_never_carries_pat(env):
    fake = FakeZitadel()
    fake.member_grant_status = 403
    output_dir = str(env / "cred")

    with pytest.raises(mod.ProvisioningError) as excinfo:
        _provision(fake, output_dir)

    assert _FAKE_PAT not in str(excinfo.value)
