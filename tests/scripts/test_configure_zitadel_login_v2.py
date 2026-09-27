"""Tests for scripts/configure_zitadel_login_v2.py (docs/ADR/0017) against
an in-memory fake ZITADEL (httpx.MockTransport), mirroring the test seam
saas-os's own infra.local_identity.zitadel_bootstrap already uses.

No real ZITADEL instance, no real PAT -- the "PAT" used here is a fixed
test string, checked never to leak into any exception message or captured
output.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts import configure_zitadel_login_v2 as mod

_FAKE_PAT = "fake-test-pat-value-should-never-leak"
_ORG_ID = "org-1"
_PROJECT_ID = "proj-1"
_PROJECT_NAME = "product"
_APPLICATION_ID = "app-1"
_APPLICATION_NAME = "product-backend"
_CLIENT_ID = "client-1"


def _application(
    *,
    client_id=_CLIENT_ID,
    application_id=_APPLICATION_ID,
    project_id=_PROJECT_ID,
    name=_APPLICATION_NAME,
    base_uri: str | None = None,
) -> dict:
    oidc_configuration: dict = {
        "clientId": client_id,
        "redirectUris": ["http://localhost:8080/auth/callback"],
        "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
        "grantTypes": ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE"],
        "authMethodType": "OIDC_AUTH_METHOD_TYPE_NONE",
    }
    if base_uri is not None:
        oidc_configuration["loginVersion"] = {"loginV2": {"baseUri": base_uri}}
    return {
        "applicationId": application_id,
        "projectId": project_id,
        "name": name,
        "oidcConfiguration": oidc_configuration,
    }


class FakeZitadel:
    """Records every call; ListApplications/UpdateApplication operate on a
    mutable in-memory application list so idempotency/update behavior can
    be observed end-to-end through `configure()`."""

    def __init__(self, projects: list[dict], applications: list[dict]) -> None:
        self.projects = projects
        self.applications = applications
        self.calls: list[tuple[str, str, dict | None]] = []
        self.seen_authorization_headers: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.seen_authorization_headers.append(request.headers.get("authorization", ""))
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))

        if path == "/management/v1/orgs/me":
            return httpx.Response(200, json={"org": {"id": _ORG_ID}})

        if path == "/zitadel.project.v2.ProjectService/ListProjects":
            return httpx.Response(200, json={"projects": self.projects})

        if path == "/zitadel.application.v2.ApplicationService/ListApplications":
            assert body is not None
            project_id = body["filters"][0]["projectIdFilter"]["projectId"]
            matches = [a for a in self.applications if a["projectId"] == project_id]
            return httpx.Response(200, json={"applications": matches})

        if path == "/zitadel.application.v2.ApplicationService/UpdateApplication":
            assert body is not None
            application_id = body["applicationId"]
            for app in self.applications:
                if app["applicationId"] == application_id:
                    base_uri = body["oidcConfiguration"]["loginVersion"]["loginV2"]["baseUri"]
                    app["oidcConfiguration"]["loginVersion"] = {"loginV2": {"baseUri": base_uri}}
            return httpx.Response(200, json={"changeDate": "2026-01-01T00:00:00Z"})

        raise AssertionError(f"unexpected request: {request.method} {path}")

    def update_calls(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[1].endswith("/UpdateApplication")]


@pytest.fixture
def pat_path(tmp_path, monkeypatch):
    path = tmp_path / "bootstrap.pat"
    path.write_text(_FAKE_PAT, encoding="utf-8")
    monkeypatch.setenv("ZITADEL_BOOTSTRAP_PAT_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def base_env(monkeypatch, pat_path):
    monkeypatch.setenv("ZITADEL_INTERNAL_URL", "http://zitadel.test")
    monkeypatch.setenv("OIDC_LOCAL_PROJECT_NAME", _PROJECT_NAME)
    monkeypatch.setenv("OIDC_LOCAL_APPLICATION_NAME", _APPLICATION_NAME)
    monkeypatch.setenv("OIDC_CLIENT_ID", _CLIENT_ID)
    monkeypatch.delenv("ZITADEL_LOGIN_V2_BASE_URI", raising=False)


def _run(fake: FakeZitadel) -> None:
    mod.configure(transport=fake.transport())


# --- Resolution --------------------------------------------------------------


def test_configured_client_id_resolves_and_updates(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri=None)],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    _run(fake)

    updated = fake.applications[0]["oidcConfiguration"]["loginVersion"]["loginV2"]["baseUri"]
    assert updated == "https://login.example.test/"


def test_wrong_client_id_fails_with_no_write(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(client_id="some-other-client")],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError, match="client_id"):
        _run(fake)

    assert fake.update_calls() == []


def test_ambiguous_client_id_fails_with_no_write(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[
            _application(application_id="app-1"),
            _application(application_id="app-2"),
        ],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError, match="found 2"):
        _run(fake)

    assert fake.update_calls() == []


def test_project_application_mismatch_fails():
    # A defensive check inside find_application(), exercised directly: the
    # server returns, for a ListApplications filtered by _PROJECT_ID, an
    # application whose own projectId field disagrees with that filter
    # (a malformed/unexpected server response) -- find_application() must
    # not trust the filter alone.
    mismatched_app = _application(project_id="a-different-project")

    def _handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/zitadel.application.v2.ApplicationService/ListApplications"
        return httpx.Response(200, json={"applications": [mismatched_app]})

    client = httpx.Client(base_url="http://zitadel.test", transport=httpx.MockTransport(_handle))

    with pytest.raises(mod.LoginV2ConfigurationError, match="projectId"):
        mod.find_application(client, _PROJECT_ID, _CLIENT_ID, None)
    client.close()


def test_application_name_mismatch_fails(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(name="unexpected-name")],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError, match="unexpected-name"):
        _run(fake)

    assert fake.update_calls() == []


# --- Idempotency ---------------------------------------------------------------


def test_already_correct_base_uri_causes_no_write(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri="https://login.example.test/")],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    _run(fake)

    assert fake.update_calls() == []


def test_different_base_uri_performs_update(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri="https://old.example.test/")],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://new.example.test/")

    _run(fake)

    assert len(fake.update_calls()) == 1
    assert (
        fake.applications[0]["oidcConfiguration"]["loginVersion"]["loginV2"]["baseUri"]
        == "https://new.example.test/"
    )


# --- Safety ----------------------------------------------------------------


def test_unrelated_oidc_fields_preserved_in_request_body(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri=None)],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    _run(fake)

    [(_, _, update_body)] = fake.update_calls()
    assert update_body is not None
    assert update_body == {
        "applicationId": _APPLICATION_ID,
        "projectId": _PROJECT_ID,
        "oidcConfiguration": {
            "loginVersion": {"loginV2": {"baseUri": "https://login.example.test/"}}
        },
    }
    # Explicitly not present: redirectUris/responseTypes/grantTypes/etc.
    assert "redirectUris" not in update_body["oidcConfiguration"]


def test_empty_configured_value_performs_no_change_and_no_calls(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri="https://already-set.example.test/")],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "")

    _run(fake)

    assert fake.calls == []
    assert (
        fake.applications[0]["oidcConfiguration"]["loginVersion"]["loginV2"]["baseUri"]
        == "https://already-set.example.test/"
    )


def test_unset_configured_value_performs_no_change_and_no_calls(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri="https://already-set.example.test/")],
    )
    monkeypatch.delenv("ZITADEL_LOGIN_V2_BASE_URI", raising=False)

    _run(fake)

    assert fake.calls == []


def test_explicit_configuration_failure_propagates(monkeypatch):
    # No project named _PROJECT_NAME exists at all.
    fake = FakeZitadel(projects=[], applications=[])
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError, match="found 0"):
        _run(fake)


def test_write_followed_by_readback_mismatch_fails(monkeypatch):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri=None)],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    # Simulate a server that accepts the write but silently stores
    # something else (ZITADEL projection lag / a server-side bug) --
    # verify_base_uri's own read-back must catch this, not trust the 200.
    original_handle = fake._handle

    def _flaky_handle(request: httpx.Request) -> httpx.Response:
        response = original_handle(request)
        if request.url.path.endswith("/UpdateApplication"):
            fake.applications[0]["oidcConfiguration"]["loginVersion"]["loginV2"]["baseUri"] = (
                "https://wrong-value.example.test/"
            )
        return response

    fake._handle = _flaky_handle  # type: ignore[method-assign]

    with pytest.raises(mod.LoginV2ConfigurationError, match="Read-back verification failed"):
        _run(fake)


# --- No secret leakage ----------------------------------------------------------


def test_credential_not_in_exception_message(monkeypatch):
    fake = FakeZitadel(projects=[], applications=[])
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError) as excinfo:
        _run(fake)

    assert _FAKE_PAT not in str(excinfo.value)


def test_credential_not_in_stdout_or_stderr(monkeypatch, capsys):
    fake = FakeZitadel(
        projects=[{"projectId": _PROJECT_ID, "name": _PROJECT_NAME}],
        applications=[_application(base_uri="https://old.example.test/")],
    )
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://new.example.test/")

    _run(fake)

    captured = capsys.readouterr()
    assert _FAKE_PAT not in captured.out
    assert _FAKE_PAT not in captured.err


def test_missing_pat_file_fails_without_leaking_path_as_value(monkeypatch, tmp_path):
    monkeypatch.setenv("ZITADEL_BOOTSTRAP_PAT_PATH", str(tmp_path / "does-not-exist.pat"))
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError, match="Could not read the bootstrap PAT"):
        mod.configure()


def test_missing_client_id_fails_closed(monkeypatch):
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.setenv("ZITADEL_LOGIN_V2_BASE_URI", "https://login.example.test/")

    with pytest.raises(mod.LoginV2ConfigurationError, match="OIDC_CLIENT_ID"):
        mod.configure()
