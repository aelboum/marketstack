"""Authentication-factor enforcement (docs/ADR/0017's CRITICAL SECURITY
REQUIREMENT).

Verified fact this module exists specifically because of:
`CreateCallback` (app/zitadel/oidc_api.py) accepts only a `session_id` +
`session_token` and mints a usable OIDC result *unconditionally* -- it
performs no factor-sufficiency check of its own (confirmed directly
against ZITADEL's own proto comment on `CreateCallback`, which warns the
resulting `callback_url` "must be treated as credentials"). `session.write`
+ `session.link` together are therefore impersonation-capable in the
hands of a caller that skips this check. This module is that check, and
`app/main.py` is written so that `create_callback()` is never reachable
without first passing `decide()` here with `sufficient=True`.

Ground truth is always a fresh `session_api.get_session()` read (never
the response of `CreateSession`/`SetSession`, which never carries
factors -- verified proto fact, see session_api.py). A factor counts as
verified only if ZITADEL's own `Session.factors.<name>.verifiedAt` is
set; this module never infers verification from a 200 response, a
session id existing, or any other proxy signal.
"""

from __future__ import annotations

from dataclasses import dataclass

# Second-factor-capable factor names as they appear on `Session.factors`
# (verified proto: `Factors{user, password, webAuthN, intent, totp,
# otpSms, otpEmail, recoveryCode}`). `user`/`password`/`intent` are not
# themselves "a second factor".
_SECOND_FACTOR_NAMES = ("totp", "otpSms", "otpEmail", "recoveryCode")

# app/user_api.py's short enum names, in the order this service prefers to
# prompt for them when more than one is registered and allowed (strongest
# first: a hardware/passkey factor beats a mailed/texted code).
#
# OTP_SMS/OTP_EMAIL are deliberately NOT in this list even though ZITADEL
# supports them: both require an extra "request a challenge" round trip
# (Session API `challenges.otpSms`/`otpEmail`, which makes ZITADEL actually
# send the code) this service does not implement a route for, and SMS/
# email delivery on the local ZITADEL instance is unverified. A user whose
# ONLY registered second factor is OTP_SMS/OTP_EMAIL hits `mfa_unavailable`
# below -- a documented, fail-closed limitation (docs/ADR/0017 non-goals),
# never a silent downgrade to password-only.
_FACTOR_PROMPT_PRIORITY = ("U2F", "TOTP")

# Maps this service's own prompt-priority names to the Session API check
# each one corresponds to, and to LoginSettings' own allow-list vocabulary.
_FACTOR_TO_SESSION_FIELD = {
    "U2F": "webAuthN",
    "TOTP": "totp",
}


def _verified(factors: dict, name: str) -> bool:
    entry = factors.get(name)
    return bool(isinstance(entry, dict) and entry.get("verifiedAt"))


def webauthn_is_strong(factors: dict) -> bool:
    """A WebAuthn factor only counts as a (multi-)factor in its own right
    when ZITADEL itself reports `userVerified: true` on it (verified
    proto comment: "can be used to determine if the factor can be
    considered as multi-factor authentication") -- a bare U2F touch
    without user verification does not."""
    entry = factors.get("webAuthN")
    return bool(isinstance(entry, dict) and entry.get("verifiedAt") and entry.get("userVerified"))


def mfa_satisfied(factors: dict) -> bool:
    if webauthn_is_strong(factors):
        return True
    return any(_verified(factors, name) for name in _SECOND_FACTOR_NAMES)


def password_or_equivalent_satisfied(factors: dict) -> bool:
    """A verified passkey (strong WebAuthn) can stand in for password --
    it is itself a full authentication event, not merely a second
    factor -- so it satisfies this even with no password check performed
    in this session at all."""
    return _verified(factors, "password") or webauthn_is_strong(factors)


@dataclass(frozen=True)
class Decision:
    sufficient: bool
    # Present only when sufficient is False -- what this ceremony must do
    # next. Never a free-text reason string a caller could use to build a
    # user-facing message revealing more than intended.
    reason: str | None = None  # "password_required" | "mfa_required" | "mfa_unavailable"
    # The Session API check name (e.g. "totp", "webAuthN") the next step
    # should attempt, when determinable from the user's registered
    # methods and the applicable policy. None means: nothing usable is
    # registered -- fail closed, do not prompt for something ZITADEL will
    # only reject.
    next_factor: str | None = None


# LoginSettings' `secondFactors`/`multiFactors` use their OWN enums
# (`SecondFactorType`/`MultiFactorType`), a *different* vocabulary from
# `AuthenticationMethodType` (verified live against the local instance,
# not just the proto): `SecondFactorType.SECOND_FACTOR_TYPE_OTP` and
# `..._TOTP` are proto `allow_alias` aliases for the same numeric value,
# and the live instance's JSON response used the deprecated `OTP` spelling
# -- normalized to this module's own "TOTP" vocabulary here so it lines up
# with `_FACTOR_PROMPT_PRIORITY`/`registered_methods` (from
# `AuthenticationMethodType`, which has no such alias).
_LOGIN_SETTINGS_FACTOR_PREFIXES = ("SECOND_FACTOR_TYPE_", "MULTI_FACTOR_TYPE_")
_LOGIN_SETTINGS_FACTOR_ALIASES = {"OTP": "TOTP", "U2F_WITH_VERIFICATION": "U2F"}


def _normalize_login_settings_factor(raw: str) -> str:
    short = raw
    for prefix in _LOGIN_SETTINGS_FACTOR_PREFIXES:
        short = short.removeprefix(prefix)
    return _LOGIN_SETTINGS_FACTOR_ALIASES.get(short, short)


def choose_next_factor(*, registered_methods: set[str], login_settings: dict) -> str | None:
    """Returns one of `_FACTOR_PROMPT_PRIORITY`'s Session-API field names
    (via `_FACTOR_TO_SESSION_FIELD`), or None if the user has no eligible
    second factor registered. `login_settings`'s own second/multi-factor
    lists are an allow-list when present; an empty/missing list is
    treated as "no additional restriction beyond what the user has
    registered" (ZITADEL's own default posture -- this service never
    widens it, only narrows against what's actually registered)."""
    raw_allowed = (login_settings.get("secondFactors") or []) + (
        login_settings.get("multiFactors") or []
    )
    allowed = {_normalize_login_settings_factor(v) for v in raw_allowed}
    for candidate in _FACTOR_PROMPT_PRIORITY:
        if candidate not in registered_methods:
            continue
        if allowed and candidate not in allowed:
            continue
        return _FACTOR_TO_SESSION_FIELD[candidate]
    return None


def decide(*, factors: dict, login_settings: dict, registered_methods: set[str]) -> Decision:
    if not password_or_equivalent_satisfied(factors):
        return Decision(sufficient=False, reason="password_required")

    force_mfa = bool(login_settings.get("forceMfa") or login_settings.get("forceMfaLocalOnly"))
    if not force_mfa:
        return Decision(sufficient=True)

    if mfa_satisfied(factors):
        return Decision(sufficient=True)

    next_factor = choose_next_factor(
        registered_methods=registered_methods, login_settings=login_settings
    )
    if next_factor is None:
        # Fail closed: MFA is required, nothing usable is registered for
        # this user, and this service does not implement enrollment
        # (docs/ADR/0017 non-goals) -- never fall back to treating
        # password alone as sufficient.
        return Decision(sufficient=False, reason="mfa_unavailable")
    return Decision(sufficient=False, reason="mfa_required", next_factor=next_factor)
