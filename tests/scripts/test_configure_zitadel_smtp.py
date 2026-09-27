"""Tests for scripts/configure_zitadel_smtp.py against an in-memory fake
ZITADEL (httpx.MockTransport), mirroring
tests/scripts/test_configure_zitadel_login_v2.py's own approach.

No real ZITADEL instance, no real PAT/SMTP password -- both are fixed test
strings, checked never to leak into any exception message or captured
output.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts import configure_zitadel_smtp as mod

_FAKE_PAT = "fake-test-pat-value-should-never-leak"
_FAKE_SMTP_PASSWORD = "fake-smtp-password-should-never-leak"
_PROVIDER_ID = "provider-1"


def _config(
    *,
    provider_id=_PROVIDER_ID,
    host="mailpit:1025",
    sender_address="noreply@product.local",
    sender_name="Product",
    tls=False,
    state="EMAIL_PROVIDER_ACTIVE",
) -> dict:
    return {
        "id": provider_id,
        "state": state,
        "smtp": {
            "host": host,
            "senderAddress": sender_address,
            "senderName": sender_name,
            "tls": tls,
        },
    }


class FakeZitadel:
    """Records every call; `providers` is a mutable in-memory list (at most
    one active at a time, matching the real API's own semantics) so
    idempotency/update/activate behavior can be observed end-to-end through
    `configure()`."""

    def __init__(self, providers: list[dict] | None = None, active_id: str | None = None) -> None:
        self.providers = providers or []
        self.active_id = active_id
        self.calls: list[tuple[str, str, dict | None]] = []
        self.seen_authorization_headers: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _find(self, provider_id: str) -> dict | None:
        for p in self.providers:
            if p["id"] == provider_id:
                return p
        return None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.seen_authorization_headers.append(request.headers.get("authorization", ""))
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        method = request.method
        self.calls.append((method, path, body))

        if method == "GET" and path == "/admin/v1/email":
            if self.active_id is None:
                return httpx.Response(404, json={"message": "SMTP configuration not found"})
            return httpx.Response(200, json={"config": self._find(self.active_id)})

        if method == "GET" and path.startswith("/admin/v1/email/"):
            provider_id = path.rsplit("/", 1)[-1]
            config = self._find(provider_id)
            if config is None:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json={"config": config})

        if method == "POST" and path == "/admin/v1/email/smtp":
            assert body is not None
            new_id = f"provider-{len(self.providers) + 1}"
            config = {
                "id": new_id,
                "state": "EMAIL_PROVIDER_INACTIVE",
                "smtp": {
                    "host": body["host"],
                    "senderAddress": body["senderAddress"],
                    "senderName": body["senderName"],
                    "tls": body.get("tls", False),
                },
            }
            self.providers.append(config)
            return httpx.Response(200, json={"id": new_id})

        if method == "PUT" and path.startswith("/admin/v1/email/smtp/"):
            assert body is not None
            provider_id = path.rsplit("/", 1)[-1]
            config = self._find(provider_id)
            assert config is not None
            config["smtp"] = {
                "host": body["host"],
                "senderAddress": body["senderAddress"],
                "senderName": body["senderName"],
                "tls": body.get("tls", False),
            }
            return httpx.Response(200, json={})

        if method == "POST" and path.endswith("/_activate"):
            provider_id = path.split("/")[-2]
            config = self._find(provider_id)
            assert config is not None
            config["state"] = "EMAIL_PROVIDER_ACTIVE"
            self.active_id = provider_id
            return httpx.Response(200, json={})

        raise AssertionError(f"unexpected request: {method} {path}")

    def write_calls(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[0] in ("POST", "PUT") and not c[1].endswith("_activate")]

    def activate_calls(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[1].endswith("/_activate")]


@pytest.fixture
def pat_path(tmp_path, monkeypatch):
    path = tmp_path / "bootstrap.pat"
    path.write_text(_FAKE_PAT, encoding="utf-8")
    monkeypatch.setenv("ZITADEL_BOOTSTRAP_PAT_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def base_env(monkeypatch, pat_path):
    monkeypatch.setenv("ZITADEL_INTERNAL_URL", "http://zitadel.test")
    monkeypatch.setenv("SMTP_SENDER_ADDRESS", "noreply@product.local")
    monkeypatch.setenv("SMTP_SENDER_NAME", "Product")
    monkeypatch.delenv("SMTP_TLS", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)


def _run(fake: FakeZitadel) -> None:
    mod.configure(transport=fake.transport())


# --- No-op / unset -----------------------------------------------------------


def test_unset_host_performs_no_change_and_no_calls(monkeypatch):
    fake = FakeZitadel()
    monkeypatch.delenv("SMTP_HOST", raising=False)

    _run(fake)

    assert fake.calls == []


def test_empty_host_performs_no_change_and_no_calls(monkeypatch):
    fake = FakeZitadel()
    monkeypatch.setenv("SMTP_HOST", "")

    _run(fake)

    assert fake.calls == []


# --- Fresh add ---------------------------------------------------------------


def test_no_existing_provider_adds_and_activates(monkeypatch):
    fake = FakeZitadel()
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")

    _run(fake)

    assert len(fake.providers) == 1
    assert fake.providers[0]["smtp"]["host"] == "mailpit:1025"
    assert fake.providers[0]["state"] == "EMAIL_PROVIDER_ACTIVE"
    assert len(fake.activate_calls()) == 1


def test_add_sends_no_auth_when_user_and_password_unset(monkeypatch):
    fake = FakeZitadel()
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")

    _run(fake)

    [(_, _, add_body)] = fake.write_calls()
    assert add_body is not None
    assert add_body["none"] == {}
    assert "plain" not in add_body


def test_add_sends_plain_auth_when_user_and_password_set(monkeypatch):
    fake = FakeZitadel()
    monkeypatch.setenv("SMTP_HOST", "smtp.postmarkapp.com:587")
    monkeypatch.setenv("SMTP_USER", "postmark-user")
    monkeypatch.setenv("SMTP_PASSWORD", _FAKE_SMTP_PASSWORD)

    _run(fake)

    [(_, _, add_body)] = fake.write_calls()
    assert add_body is not None
    assert add_body["plain"] == {"username": "postmark-user", "password": _FAKE_SMTP_PASSWORD}
    assert "none" not in add_body


# --- Idempotency ---------------------------------------------------------------


def test_matching_active_provider_causes_no_write(monkeypatch):
    fake = FakeZitadel(providers=[_config()], active_id=_PROVIDER_ID)
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")

    _run(fake)

    assert fake.write_calls() == []
    assert fake.activate_calls() == []


def test_different_settings_updates_existing_provider(monkeypatch):
    fake = FakeZitadel(providers=[_config(host="old-host:1025")], active_id=_PROVIDER_ID)
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")

    _run(fake)

    assert len(fake.providers) == 1
    assert fake.providers[0]["smtp"]["host"] == "mailpit:1025"
    put_calls = [c for c in fake.calls if c[0] == "PUT"]
    assert len(put_calls) == 1


def test_different_sender_address_updates_existing_provider(monkeypatch):
    fake = FakeZitadel(
        providers=[_config(sender_address="old@example.test")], active_id=_PROVIDER_ID
    )
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")

    _run(fake)

    assert fake.providers[0]["smtp"]["senderAddress"] == "noreply@product.local"


# --- No secret leakage ----------------------------------------------------------


def test_credential_not_in_exception_message(monkeypatch):
    class BrokenTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")
    monkeypatch.setattr(mod, "_RETRIES", 1)
    monkeypatch.setattr(mod, "_RETRY_DELAY_SECONDS", 0.0)

    with pytest.raises(mod.SmtpConfigurationError) as excinfo:
        mod.configure(transport=BrokenTransport())

    assert _FAKE_PAT not in str(excinfo.value)


def test_credential_not_in_stdout_or_stderr(monkeypatch, capsys):
    fake = FakeZitadel()
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")
    monkeypatch.setenv("SMTP_USER", "postmark-user")
    monkeypatch.setenv("SMTP_PASSWORD", _FAKE_SMTP_PASSWORD)

    _run(fake)

    captured = capsys.readouterr()
    assert _FAKE_PAT not in captured.out
    assert _FAKE_PAT not in captured.err
    assert _FAKE_SMTP_PASSWORD not in captured.out
    assert _FAKE_SMTP_PASSWORD not in captured.err


def test_missing_pat_file_fails_without_leaking_path_as_value(monkeypatch, tmp_path):
    monkeypatch.setenv("ZITADEL_BOOTSTRAP_PAT_PATH", str(tmp_path / "does-not-exist.pat"))
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")

    with pytest.raises(mod.SmtpConfigurationError, match="Could not read the bootstrap PAT"):
        mod.configure()


def test_explicit_configuration_failure_propagates(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit:1025")
    monkeypatch.setattr(mod, "_RETRIES", 1)
    monkeypatch.setattr(mod, "_RETRY_DELAY_SECONDS", 0.0)

    def _always_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "internal error"})

    with pytest.raises(mod.SmtpConfigurationError, match="failed after"):
        mod.configure(transport=httpx.MockTransport(_always_fail))
