"""The production AI boundary: closed capability vocabulary and
fail-closed provider/registry (docs/ROADMAP.md Phase 9.4,
`product/ai/capabilities.py`, `product/ai/production.py`). No database,
no network -- a plain unit test, part of the default `pytest` run.

The central property proven here is the one this phase exists to
guarantee: **production AI execution cannot be enabled by accident**.
Before docs/ROADMAP.md Phase 26, this held because no AI vendor had been
approved at all; since Phase 26 (OpenAI approved, see the "OpenAI
production registration" section below), it holds because an
*unconfigured* environment (no `OPENAI_API_KEY`/`OPENAI_MODEL` set) still
fails closed exactly as before -- registration is never automatic, and a
test-double provider can still never become production regardless of
what is configured.
"""

from __future__ import annotations

import pytest
from control_plane.orchestration.errors import ToolNotFoundError
from product.ai.capabilities import (
    PRODUCTION_CAPABILITIES,
    resource_type_for,
    validate_capability,
)
from product.ai.errors import AIProviderNotConfiguredError, AIValidationError
from product.ai.openai_config import get_openai_config
from product.ai.openai_provider import OpenAIProvider
from product.ai.policy import PLATFORM_PROVIDER_POLICY
from product.ai.production import (
    clear_production_llm_provider,
    configure_production_llm_provider_from_environment,
    get_production_llm_provider,
    production_llm_provider_configured,
    production_tool_registry,
    register_production_llm_provider,
)
from product.ai.provider import FakeLLMProvider, LLMCompletion
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY


@pytest.fixture(autouse=True)
def _restore_unconfigured_provider():
    """Every test in this module starts and ends with production
    unconfigured -- the system's correct resting state."""
    clear_production_llm_provider()
    yield
    clear_production_llm_provider()


# --- closed production capability vocabulary -------------------------------


def test_the_smallest_capability_is_the_only_approved_one() -> None:
    assert PRODUCTION_CAPABILITIES == frozenset({QUALIFY_LEAD_TOOL_KEY})


def test_receptionist_advice_is_not_production_approved() -> None:
    """Deliberately excluded: its payload carries a raw free-text call
    transcript (`product/ai/capabilities.py`'s own docstring)."""
    assert "ai.telephony.receptionist_advice" not in PRODUCTION_CAPABILITIES
    with pytest.raises(AIValidationError):
        validate_capability("ai.telephony.receptionist_advice")


def test_unknown_capability_is_rejected() -> None:
    for unknown in ("", "ai.crm.qualify", "exfiltrate_everything", "ai.crm.qualify_lead "):
        with pytest.raises(AIValidationError):
            validate_capability(unknown)


def test_every_approved_capability_declares_a_resource_type() -> None:
    for capability in PRODUCTION_CAPABILITIES:
        assert resource_type_for(capability)
    assert resource_type_for(QUALIFY_LEAD_TOOL_KEY) == "crm.contact"


# --- fail-closed production provider ---------------------------------------


def test_production_provider_is_unconfigured_by_default() -> None:
    assert production_llm_provider_configured() is False


def test_getting_the_production_provider_fails_closed() -> None:
    with pytest.raises(AIProviderNotConfiguredError):
        get_production_llm_provider()


def test_building_the_production_registry_fails_closed() -> None:
    """Missing production provider configuration must fail closed --
    never fall back to a default or a test double."""
    with pytest.raises(AIProviderNotConfiguredError):
        production_tool_registry()


def test_fake_provider_cannot_become_the_production_provider() -> None:
    """The single most important negative guarantee of this phase: the
    deterministic test double cannot be wired into production, so
    synthetic output can never reach a real tenant."""
    with pytest.raises(AIValidationError):
        register_production_llm_provider(FakeLLMProvider())
    assert production_llm_provider_configured() is False
    with pytest.raises(AIProviderNotConfiguredError):
        production_tool_registry()


@pytest.mark.parametrize("name", ["fake", "stub", "mock", "test"])
def test_every_test_double_name_is_refused(name: str) -> None:
    class _Double:
        @property
        def name(self) -> str:
            return name

        def complete(self, *, system_prompt, user_content, max_output_chars):
            raise AssertionError("must never be called")

    with pytest.raises(AIValidationError):
        register_production_llm_provider(_Double())
    assert production_llm_provider_configured() is False


def test_a_real_adapter_would_build_only_the_approved_capabilities() -> None:
    """Proves the registry construction path itself is correct and
    deterministic, using a stand-in that is *not* one of the refused test
    -double names. This does not make production executable -- nothing
    registers this provider outside this test, and no such adapter exists
    in the repository."""

    class _HypotheticalVendorProvider:
        @property
        def name(self) -> str:
            return "hypothetical-vendor"

        def complete(self, *, system_prompt, user_content, max_output_chars):
            return LLMCompletion(text="", provider_name=self.name)

    register_production_llm_provider(_HypotheticalVendorProvider())
    assert production_llm_provider_configured() is True

    registry = production_tool_registry()
    assert registry.get(QUALIFY_LEAD_TOOL_KEY).key == QUALIFY_LEAD_TOOL_KEY
    # Only the approved capability is registered -- the other four Phase 9
    # tools are not production-registered by this phase.
    for unapproved in (
        "ai.telephony.receptionist_advice",
        "ai.conversations.summarize",
        "ai.conversations.suggest_reply",
        "ai.crm.suggest_next_actions",
    ):
        with pytest.raises(ToolNotFoundError):
            registry.get(unapproved)


def test_registry_build_is_deterministic_across_calls() -> None:
    class _HypotheticalVendorProvider:
        @property
        def name(self) -> str:
            return "hypothetical-vendor"

        def complete(self, *, system_prompt, user_content, max_output_chars):
            return LLMCompletion(text="", provider_name=self.name)

    register_production_llm_provider(_HypotheticalVendorProvider())
    first = production_tool_registry()
    second = production_tool_registry()
    assert first.get(QUALIFY_LEAD_TOOL_KEY).key == second.get(QUALIFY_LEAD_TOOL_KEY).key


def test_importing_product_ai_registers_no_production_provider() -> None:
    """Registration is an explicit call, never an import side effect."""
    import importlib

    import product.ai
    import product.ai.tools.lead_qualification

    importlib.reload(product.ai)
    assert production_llm_provider_configured() is False


# --- OpenAI production registration (docs/ROADMAP.md Phase 26) --------------


def test_openai_is_platform_eligible() -> None:
    assert "openai" in PLATFORM_PROVIDER_POLICY.eligible_providers


def test_fake_remains_platform_eligible_alongside_openai() -> None:
    """Phase 26 adds `"openai"`; it must never remove `"fake"` -- existing
    tests elsewhere (`tests/ai/test_automation_action_integration.py`)
    depend on `"fake"`-shaped test doubles remaining platform-eligible."""
    assert "fake" in PLATFORM_PROVIDER_POLICY.eligible_providers


def test_openai_registers_and_is_retrievable_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SDK call happens here -- constructing `openai.OpenAI(...)`
    performs no network I/O (verified: only `complete()` does), so this
    proves real registration/retrieval without mocking the SDK client."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")
    get_openai_config.cache_clear()
    try:
        provider = OpenAIProvider()
        register_production_llm_provider(provider)

        assert production_llm_provider_configured() is True
        assert get_production_llm_provider() is provider
        assert get_production_llm_provider().name == "openai"

        registry = production_tool_registry()
        assert registry.get(QUALIFY_LEAD_TOOL_KEY).key == QUALIFY_LEAD_TOOL_KEY
    finally:
        get_openai_config.cache_clear()


def test_configure_from_environment_registers_openai_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`configure_production_llm_provider_from_environment()` is the one
    real composition-root call (`product/api/main.py`,
    `product/production_worker_entrypoint.py`) -- proves it actually
    registers OpenAI end-to-end from nothing but environment state."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")
    get_openai_config.cache_clear()
    try:
        configure_production_llm_provider_from_environment()
        assert production_llm_provider_configured() is True
        assert get_production_llm_provider().name == "openai"
    finally:
        get_openai_config.cache_clear()


def test_configure_from_environment_is_a_harmless_noop_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition-root call must never crash application startup in
    an environment with no OpenAI credential -- mirrors `core/email`'s own
    "must not crash unrelated application startup unless email is
    explicitly configured as mandatory" precedent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    get_openai_config.cache_clear()
    try:
        configure_production_llm_provider_from_environment()
        assert production_llm_provider_configured() is False
        with pytest.raises(AIProviderNotConfiguredError):
            get_production_llm_provider()
    finally:
        get_openai_config.cache_clear()
