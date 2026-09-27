"""Confirms the successful flow's only integration point with SaaS-OS is
an HTTP redirect to its existing, unmodified `/auth/callback` -- and that
this codebase has no import dependency on SaaS-OS at all (docs/ADR/0017's
hard architectural boundary)."""

from __future__ import annotations

import ast
import pathlib

from tests.test_auth_request import _extract_csrf

_APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

_FORBIDDEN_IMPORT_ROOTS = {"saas_os", "product", "core", "api", "infra"}


def test_successful_login_redirects_to_saas_os_auth_callback(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_saas_os")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_saas_os"})
    csrf = _extract_csrf(start.text)

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/auth/callback" in response.headers["location"]


def test_no_module_in_this_service_imports_saas_os_or_product_code():
    for path in _APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            forbidden = roots & _FORBIDDEN_IMPORT_ROOTS
            assert not forbidden, f"{path} imports forbidden module(s): {forbidden}"
