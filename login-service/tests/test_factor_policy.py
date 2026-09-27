"""Unit tests for the CRITICAL SECURITY REQUIREMENT enforcement logic
(docs/ADR/0017) -- `CreateCallback` must never be reachable when the
required authentication policy is unsatisfied."""

from __future__ import annotations

from app import factor_policy


def test_password_only_no_mfa_required_is_sufficient():
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": False}, registered_methods={"PASSWORD"}
    )
    assert decision.sufficient is True


def test_no_password_no_strong_webauthn_is_insufficient():
    factors = {"user": {"id": "u1"}}
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": False}, registered_methods={"PASSWORD"}
    )
    assert decision.sufficient is False
    assert decision.reason == "password_required"


def test_password_only_session_cannot_bypass_required_mfa():
    """The exact scenario the audit flagged: CreateSession(password) alone
    must never be treated as sufficient when forceMfa is true."""
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": True}, registered_methods={"PASSWORD", "TOTP"}
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_required"
    assert decision.next_factor == "totp"


def test_password_plus_verified_totp_satisfies_forced_mfa():
    factors = {
        "user": {"id": "u1"},
        "password": {"verifiedAt": "t"},
        "totp": {"verifiedAt": "t"},
    }
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": True}, registered_methods={"PASSWORD", "TOTP"}
    )
    assert decision.sufficient is True


def test_weak_webauthn_without_user_verified_does_not_satisfy_mfa():
    factors = {
        "user": {"id": "u1"},
        "password": {"verifiedAt": "t"},
        "webAuthN": {"verifiedAt": "t", "userVerified": False},
    }
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": True}, registered_methods={"PASSWORD", "U2F"}
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_required"


def test_strong_webauthn_satisfies_mfa_and_can_replace_password():
    factors = {
        "user": {"id": "u1"},
        "webAuthN": {"verifiedAt": "t", "userVerified": True},
    }
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": True}, registered_methods={"PASSKEY"}
    )
    assert decision.sufficient is True


def test_mfa_required_but_nothing_registered_fails_closed():
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors, login_settings={"forceMfa": True}, registered_methods={"PASSWORD"}
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_unavailable"
    assert decision.next_factor is None


def test_mfa_required_but_only_unsupported_otp_registered_fails_closed():
    """OTP_SMS/OTP_EMAIL are recognized but not wired up -- must not be
    silently treated as satisfying or bypassing the requirement."""
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors,
        login_settings={"forceMfa": True},
        registered_methods={"PASSWORD", "OTP_SMS"},
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_unavailable"


def test_second_factors_allowlist_is_respected():
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors,
        login_settings={"forceMfa": True, "secondFactors": ["SECOND_FACTOR_TYPE_TOTP"]},
        registered_methods={"PASSWORD", "U2F"},  # registered but not allow-listed
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_unavailable"


def test_second_factors_allowlist_accepts_deprecated_otp_alias_for_totp():
    """Live-verified against the real local ZITADEL instance: LoginSettings
    serializes this value as `SECOND_FACTOR_TYPE_OTP` (the proto's own
    `allow_alias` deprecated name for the same numeric value as
    `SECOND_FACTOR_TYPE_TOTP`), not `..._TOTP` -- a naive `.removeprefix()`
    without this alias would incorrectly treat TOTP as never allow-listed."""
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors,
        login_settings={"forceMfa": True, "secondFactors": ["SECOND_FACTOR_TYPE_OTP"]},
        registered_methods={"PASSWORD", "TOTP"},
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_required"
    assert decision.next_factor == "totp"


def test_multi_factors_allowlist_uses_its_own_enum_shape():
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors,
        login_settings={
            "forceMfa": True,
            "secondFactors": [],
            "multiFactors": ["MULTI_FACTOR_TYPE_U2F_WITH_VERIFICATION"],
        },
        registered_methods={"PASSWORD", "U2F"},
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_required"
    assert decision.next_factor == "webAuthN"


def test_force_mfa_local_only_also_enforces():
    factors = {"user": {"id": "u1"}, "password": {"verifiedAt": "t"}}
    decision = factor_policy.decide(
        factors=factors,
        login_settings={"forceMfa": False, "forceMfaLocalOnly": True},
        registered_methods={"PASSWORD", "TOTP"},
    )
    assert decision.sufficient is False
    assert decision.reason == "mfa_required"
