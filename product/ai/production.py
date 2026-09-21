"""The production AI execution boundary (docs/ROADMAP.md Phase 9.4):
production provider selection and the production tool registry.

**No AI vendor has been approved in this repository, and this module does
not pick one.** Searched before writing this: `docs/INTEGRATIONS.md` and
`docs/RESPONSIBILITY-MATRIX.md` mention "Claude/OpenAI/etc." only as
illustrative examples of the Category D class sitting *behind* the Data
Authorization boundary, never as a decision; `docs/RISKS-AND-OPEN-
QUESTIONS.md` item 6 enumerates the still-open provider decisions and
names SMS, WhatsApp, telephony, and calendar sync -- not LLM. So there is
no approved provider to configure, and inventing one here would be a
decision this phase has no authority to make.

**What that means concretely: production AI execution fails closed.**
`get_production_llm_provider()` raises `AIProviderNotConfiguredError`
unless a real adapter has been registered, and none is registered,
because none exists. `production_tool_registry()` therefore cannot be
built either. This is the intended resting state, not a gap to work
around -- and it is enforced structurally rather than by convention:

- **The Fake provider can never become the production provider.**
  `register_production_llm_provider()` rejects any provider whose `name`
  is in `_NON_PRODUCTION_PROVIDER_NAMES`, so wiring `FakeLLMProvider`
  into the production path raises instead of silently succeeding. The
  Fake provider remains exactly what it has always been: a deterministic
  test double, used by tests that construct their own registry.
- **Production registration is explicit, not an import side effect.**
  A provider is registered by an explicit call, and the production
  registry is *built on demand* from the approved capability list, so
  importing `product.ai` (or anything else) registers nothing and changes
  nothing.
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
    composition root once a real vendor has been approved and an adapter
    written -- there is no such adapter in this repository today, so in
    practice nothing calls this outside tests that verify the boundary
    itself.

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
    docstring for why the absence of a provider is the correct and
    intended production state today."""
    if _production_provider is None:
        raise AIProviderNotConfiguredError(
            "no production AI provider is configured -- no AI vendor has been approved "
            "for this product, so production AI execution is disabled. See "
            "product/ai/production.py's own module docstring."
        )
    return _production_provider


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
    "get_production_llm_provider",
    "production_llm_provider_configured",
    "production_tool_registry",
    "register_production_llm_provider",
]
