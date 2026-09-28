"""The production AI execution boundary (docs/ROADMAP.md Phase 9.4):
production provider selection and the production tool registry.

**OpenAI is the approved production vendor (docs/ROADMAP.md Phase 26).**
`product/ai/openai_provider.py::OpenAIProvider` is the one concrete
`LLMProvider` adapter this repository registers, wired in through this
module's own `configure_production_llm_provider_from_environment()`
below -- never a second vendor, never a multi-provider registry. Before
Phase 26, no vendor had been approved at all (`docs/RISKS-AND-OPEN-
QUESTIONS.md` item 6 named only SMS/WhatsApp/telephony/calendar-sync as
open provider decisions, never LLM); that gap is what this phase closes.

**Being approved is not the same as being configured in every
environment.** `configure_production_llm_provider_from_environment()`
only registers `OpenAIProvider` when `OPENAI_API_KEY`/`OPENAI_MODEL` are
both actually set in the current process's own environment -- an
environment without them (a test process, a local dev machine with no
`.env` configured) still leaves `get_production_llm_provider()` raising
`AIProviderNotConfiguredError`, the identical fail-closed behavior this
module has always had. This is deployment-configuration incompleteness,
never worked around by silently substituting the deterministic
`FakeLLMProvider`:

- **The Fake provider can never become the production provider.**
  `register_production_llm_provider()` rejects any provider whose `name`
  is in `_NON_PRODUCTION_PROVIDER_NAMES`, so wiring `FakeLLMProvider`
  into the production path raises instead of silently succeeding. The
  Fake provider remains exactly what it has always been: a deterministic
  test double, used by tests that construct their own registry.
- **Production registration is explicit, not an import side effect.**
  `configure_production_llm_provider_from_environment()` is called once
  by each real process's own composition root
  (`product/api/main.py::create_app()`,
  `product/production_worker_entrypoint.py`) -- importing `product.ai`
  (or anything else) registers nothing and changes nothing.
- **Only approved capabilities are ever registered.**
  `production_tool_registry()` builds from
  `product/ai/capabilities.py::PRODUCTION_CAPABILITIES` -- the closed
  vocabulary -- never from "every tool that happens to exist". The other
  four Phase 9 tools are not production-registered by this phase.

**Why this is not registered into `control_plane.orchestration
.default_registry()`.** That global registry is process-wide and
import-order sensitive; `invoke_product_ai_tool()` already accepts an
explicit `registry=`, so the production path passes this one in
deliberately. `product/ai/__init__.py`'s own long-standing reason for
registering nothing globally -- a Fake-backed tool must never return
synthetic output to a real tenant -- is preserved exactly, and
strengthened: now it *cannot*, because a Fake-backed provider is refused
at the production boundary outright.
"""

from __future__ import annotations

from control_plane.orchestration import ToolRegistry

from product.ai.capabilities import PRODUCTION_CAPABILITIES
from product.ai.errors import AIProviderNotConfiguredError, AIValidationError
from product.ai.provider import LLMProvider
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY
from product.ai.tools.lead_qualification import build_lead_qualification_tool

#: Provider names that are test doubles and must never be accepted as the
#: production provider, however they are wired.
_NON_PRODUCTION_PROVIDER_NAMES = frozenset({"fake", "stub", "mock", "test"})

#: Builders for every capability in the closed production vocabulary.
#: A capability approved in `capabilities.py` without a builder here is a
#: configuration error surfaced at registry-build time, never a silently
#: missing tool.
_PRODUCTION_TOOL_BUILDERS = {
    QUALIFY_LEAD_TOOL_KEY: build_lead_qualification_tool,
}

_production_provider: LLMProvider | None = None


def register_production_llm_provider(provider: LLMProvider) -> None:
    """Register the production `LLMProvider`. Called by a deployment's own
    composition root -- `configure_production_llm_provider_from_environment()`
    below is the one production call site (Phase 26); a test that
    exercises this boundary directly is the other.

    Refuses any test-double provider by name, which is what makes
    "the Fake provider silently becomes production" unrepresentable
    rather than merely discouraged."""
    name = provider.name
    if name in _NON_PRODUCTION_PROVIDER_NAMES:
        raise AIValidationError(
            f"{name!r} is a non-production provider and cannot be registered as the "
            f"production AI provider."
        )
    global _production_provider
    _production_provider = provider


def clear_production_llm_provider() -> None:
    """Reset the production provider to unconfigured. Exists so a test
    that exercises the registration boundary can restore the default
    fail-closed state; production code never calls it."""
    global _production_provider
    _production_provider = None


def production_llm_provider_configured() -> bool:
    return _production_provider is not None


def get_production_llm_provider() -> LLMProvider:
    """The configured production provider, or `AIProviderNotConfiguredError`.

    No fallback, no default, no Fake substitution -- see this module's own
    docstring for why an unconfigured environment fails closed rather than
    silently substituting one."""
    if _production_provider is None:
        raise AIProviderNotConfiguredError(
            "no production AI provider is configured in this environment -- "
            "OPENAI_API_KEY/OPENAI_MODEL may be unset here, so production AI "
            "execution is disabled. See product/ai/production.py's own module "
            "docstring."
        )
    return _production_provider


def configure_production_llm_provider_from_environment() -> None:
    """Explicit, idempotent composition-root call (docs/ROADMAP.md Phase
    26) -- never an import-time side effect. Builds and registers the
    OpenAI adapter (`product/ai/openai_provider.py::OpenAIProvider`) when
    `OPENAI_API_KEY`/`OPENAI_MODEL` are both configured in this process's
    own environment; does nothing otherwise, leaving
    `get_production_llm_provider()` in its existing fail-closed state
    (mirrors `core/email`'s own "must not crash unrelated application
    startup unless email is explicitly configured as mandatory" posture --
    a test or local-dev environment with no OpenAI credential set must
    keep booting normally, exactly as it does today).

    Called once from each real process's own startup composition root
    (`product/api/main.py::create_app()`,
    `product/production_worker_entrypoint.py`) -- never from a module's
    own import, mirroring `product/action_registry_composition.py
    ::wire_production_automation_actions()`'s identical "explicit call,
    not an import side effect" discipline. Safe to call more than once in
    the same process: re-registering the same already-configured provider
    is a harmless re-assignment, not an error. Not called from any test --
    tests that need a configured production provider register their own
    explicitly, mirroring every other test's own precedent in this
    module."""
    from product.ai.openai_provider import OpenAIProvider

    try:
        provider = OpenAIProvider()
    except AIProviderNotConfiguredError:
        return
    register_production_llm_provider(provider)


def production_tool_registry() -> ToolRegistry:
    """Build a `ToolRegistry` containing exactly the approved production
    capabilities, bound to the configured production provider.

    Built fresh on each call from the closed capability vocabulary, so the
    result depends only on that vocabulary and the configured provider --
    never on import order, and never on what some other module happened to
    register. Raises `AIProviderNotConfiguredError` when no production
    provider is configured, which is the current state."""
    provider = get_production_llm_provider()
    registry = ToolRegistry()
    for capability in sorted(PRODUCTION_CAPABILITIES):
        builder = _PRODUCTION_TOOL_BUILDERS.get(capability)
        if builder is None:
            raise AIValidationError(
                f"approved production capability {capability!r} has no registered tool builder."
            )
        registry.register(builder(provider))
    return registry


__all__ = [
    "clear_production_llm_provider",
    "configure_production_llm_provider_from_environment",
    "get_production_llm_provider",
    "production_llm_provider_configured",
    "production_tool_registry",
    "register_production_llm_provider",
]
