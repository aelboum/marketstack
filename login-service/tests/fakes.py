"""In-memory fake ZITADEL, standing in for `app.main.zitadel`
(a `ZitadelClient`-shaped object -- `.request(method, path, *, json=,
params=)`) in every test. Mirrors the real, verified REST shapes each
`app/zitadel/*_api.py` module targets; never a real network call, never a
real credential.
"""

from __future__ import annotations

import time
import uuid

from app.zitadel.client import ZitadelApiError


class FakeZitadel:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}  # login_name -> user record
        self.users_by_id: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}  # session_id -> {token, factors, user_id}
        self.auth_requests: dict[str, dict] = {}
        self.login_settings: dict = {"forceMfa": False, "secondFactors": [], "multiFactors": []}
        self.deleted_session_ids: list[str] = []
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.valid_totp_code = "123456"
        self.valid_webauthn_credential_id = "valid-credential"

    # --- test setup helpers ------------------------------------------------

    def add_user(self, *, login_name: str, password: str, methods: set[str] | None = None) -> str:
        user_id = str(uuid.uuid4())
        record = {
            "user_id": user_id,
            "login_name": login_name,
            "password": password,
            "methods": methods or {"PASSWORD"},
        }
        self.users[login_name] = record
        self.users_by_id[user_id] = record
        return user_id

    def add_auth_request(self, auth_request_id: str) -> None:
        self.auth_requests[auth_request_id] = {
            "id": auth_request_id,
            "clientId": "test-client",
            "scope": ["openid"],
            "redirectUri": "http://localhost:8080/auth/callback",
        }

    # --- ZitadelClient-shaped interface -------------------------------------

    def request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> dict:
        self.calls.append((method, path, json, params))

        if method == "GET" and path.startswith("/v2/oidc/auth_requests/"):
            auth_request_id = path.rsplit("/", 1)[-1]
            auth_request = self.auth_requests.get(auth_request_id)
            if auth_request is None:
                raise ZitadelApiError(404, "auth request not found")
            return {"authRequest": auth_request}

        if method == "POST" and path.startswith("/v2/oidc/auth_requests/"):
            assert json is not None
            session_ref = json["session"]
            session = self.sessions.get(session_ref["sessionId"])
            if session is None or session["token"] != session_ref["sessionToken"]:
                raise ZitadelApiError(401, "invalid session")
            return {
                "callbackUrl": (
                    f"http://localhost:8080/auth/callback?code=fake-code"
                    f"&state=fake-state&session={session_ref['sessionId']}"
                )
            }

        if method == "POST" and path == "/v2/sessions":
            return self._create_session(json or {})

        if method == "PATCH" and path.startswith("/v2/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            return self._set_session(session_id, json or {})

        if method == "GET" and path.startswith("/v2/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            return self._get_session(session_id, params or {})

        if method == "DELETE" and path.startswith("/v2/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            self.sessions.pop(session_id, None)
            self.deleted_session_ids.append(session_id)
            return {}

        if method == "GET" and path == "/v2/settings/login":
            return {"settings": self.login_settings}

        if method == "GET" and path.endswith("/authentication_methods"):
            user_id = path.split("/")[3]
            user = self.users_by_id.get(user_id)
            methods = user["methods"] if user else set()
            return {"authMethodTypes": [f"AUTHENTICATION_METHOD_TYPE_{m}" for m in methods]}

        raise AssertionError(f"unexpected fake ZITADEL request: {method} {path}")

    # --- internals -----------------------------------------------------------

    def _create_session(self, body: dict) -> dict:
        checks = body.get("checks", {})
        login_name = checks.get("user", {}).get("loginName")
        user = self.users.get(login_name)
        factors: dict = {}
        if user is not None:
            factors["user"] = {
                "id": user["user_id"],
                "loginName": login_name,
                "verifiedAt": _now(),
            }
        password_check = checks.get("password", {}).get("password")
        if password_check is not None:
            if user is None or user["password"] != password_check:
                raise ZitadelApiError(401, "invalid credentials")
            factors["password"] = {"verifiedAt": _now()}

        session_id = str(uuid.uuid4())
        token = str(uuid.uuid4())
        self.sessions[session_id] = {
            "token": token,
            "factors": factors,
            "user_id": user["user_id"] if user else None,
        }
        response: dict = {"sessionId": session_id, "sessionToken": token}
        challenges = body.get("challenges")
        if challenges:
            response["challenges"] = self._build_challenges(challenges)
        return response

    def _set_session(self, session_id: str, body: dict) -> dict:
        session = self.sessions.get(session_id)
        if session is None or session["token"] != body.get("sessionToken"):
            raise ZitadelApiError(401, "invalid session")

        checks = body.get("checks", {})
        if "totp" in checks:
            if checks["totp"]["code"] != self.valid_totp_code:
                raise ZitadelApiError(401, "invalid totp code")
            session["factors"]["totp"] = {"verifiedAt": _now()}
        if "webAuthN" in checks:
            assertion = checks["webAuthN"]["credentialAssertionData"]
            if assertion.get("id") != self.valid_webauthn_credential_id:
                raise ZitadelApiError(401, "invalid webauthn assertion")
            session["factors"]["webAuthN"] = {"verifiedAt": _now(), "userVerified": True}

        # Rotate the token on every SetSession call -- mirrors the real API.
        new_token = str(uuid.uuid4())
        session["token"] = new_token
        response: dict = {"sessionId": session_id, "sessionToken": new_token}
        challenges = body.get("challenges")
        if challenges:
            response["challenges"] = self._build_challenges(challenges)
        return response

    def _build_challenges(self, requested: dict) -> dict:
        result: dict = {}
        if "webAuthN" in requested:
            result["webAuthN"] = {
                "publicKeyCredentialRequestOptions": {
                    "publicKey": {
                        "challenge": "ZmFrZS1jaGFsbGVuZ2U",
                        "rpId": requested["webAuthN"].get("domain", "localhost"),
                        "timeout": 60000,
                        "userVerification": requested["webAuthN"].get(
                            "userVerificationRequirement", "required"
                        ),
                        "allowCredentials": [],
                    }
                }
            }
        return result

    def _get_session(self, session_id: str, params: dict) -> dict:
        # Mirrors live-verified real ZITADEL behavior (security audit
        # F-04): our privileged IAM_LOGIN_CLIENT-equivalent credential
        # already holds session.read unconditionally, so GetSession here
        # never requires -- and the real client never sends -- a
        # sessionToken query parameter. `params` is accepted only for
        # call-shape compatibility with the generic `request()` dispatch
        # below; it is not used to authorize this read.
        session = self.sessions.get(session_id)
        if session is None:
            raise ZitadelApiError(401, "invalid session")
        return {"session": {"id": session_id, "factors": session["factors"]}}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def create_callback_calls(fake: FakeZitadel) -> list[tuple[str, str, dict | None, dict | None]]:
    """Every test that must prove `CreateCallback` was (or was not)
    reached uses this instead of re-deriving the same filter."""
    return [c for c in fake.calls if c[0] == "POST" and "auth_requests" in c[1]]
