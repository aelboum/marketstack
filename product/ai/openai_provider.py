"""The OpenAI `LLMProvider` adapter (docs/ROADMAP.md Phase 26) -- the one
concrete implementation of `product/ai/provider.py::LLMProvider` this
phase adds, behind the existing neutral boundary. This is the only file
in this repository that imports the `openai` SDK (mirrors
`core/email/smtp_provider.py`'s own "only the concrete adapter knows the
vendor's specific shape" precedent for `smtplib`).

**No change to the generic contract.** `LLMProvider`/`LLMCompletion`
(`product/ai/provider.py`) are used entirely unchanged -- `name`,
`complete(*, system_prompt, user_content, max_output_chars) ->
LLMCompletion(text, provider_name)`. This adapter translates that neutral
shape into the current OpenAI Responses API
(`client.responses.create(model=..., instructions=..., input=...,
max_output_tokens=...)`, `response.output_text` for the result -- see
https://github.com/openai/openai-python and
https://developers.openai.com/api/docs/libraries, the Responses API being
OpenAI's own current primary text-generation interface, Chat Completions
remaining supported but not preferred) -- Responses-specific concepts
(the `instructions`/`input` split, `output_text`) stay entirely inside
this module and never leak into `LLMProvider` itself.

**Credential.** `OPENAI_API_KEY` is read once, at construction time,
through `infra.secrets.get_secrets_provider()` -- never `os.environ`
directly, never stored anywhere outside this one instance's private
`_client` attribute, never logged, and never included in any exception
this module raises (mirrors `core/email/smtp_provider.py`'s own identical
`SMTP_USERNAME`/`SMTP_PASSWORD` discipline exactly). Missing
configuration (`OPENAI_API_KEY` or `OPENAI_MODEL`) raises
`AIProviderNotConfiguredError` -- fails closed, the same "intended
resting state, not a misconfiguration to silently work around" posture
`product/ai/production.py` already establishes.

**Platform-level, not tenant-scoped.** One `OpenAIProvider` instance
holds one platform credential and one platform-configured model; it is
constructed by the composition root once and registered via
`product/ai/production.py::register_production_llm_provider()`. It never
receives, stores, or reasons about `tenant_id`, a tenant's own policy, or
a tenant's own credential -- `complete()`'s only inputs are the bounded
`system_prompt`/`user_content`/`max_output_chars` the existing
`LLMProvider` contract already carries; tenant context stays entirely in
`product/ai/invocation.py`'s own call chain, upstream of this adapter.

**No second retry loop -- the SDK's own is explicitly disabled too**
(security/correctness audit finding MEDIUM-2). No `while`/`sleep`/backoff
loop exists in this module -- mirrors `core/email/smtp_provider.py`'s own
explicit "no retry loop exists in this module at all... a failed call
raises `EmailProviderError` exactly once" precedent. The OpenAI SDK's own
built-in transient-error retries default to `max_retries=2` -- left at
that default, a single `complete()` call could make up to three HTTP
attempts, invisible to and un-coordinated with the durable workflow
engine's own `RetryPolicy`, and able to exceed
`product/automation/durable/production_workflow.py::_ACTION_ACTIVITY_TIMEOUT`
(60s) before the SDK's own internal attempts even finish -- Temporal would
then kill and retry the whole activity on top of the SDK's own unfinished
retry, stacking two independent retry mechanisms. `max_retries=0` below
closes this: exactly one HTTP attempt per `complete()` call, so the
durable workflow's own `RetryPolicy`
(`product/automation/durable/business_activities.py`, unchanged) remains
the sole owner of retry semantics for the `WorkflowActionExecutionError`
`product/ai/automation_action.py` already classifies an `AIProviderError`
into. The bounded, explicit request `timeout` below is unchanged by this
fix, mirroring `EmailConfig.timeout_seconds` being passed straight to
`smtplib.SMTP(...)`'s own timeout parameter for the identical "a hung/
unreachable vendor endpoint must never block a caller indefinitely"
reason.

**Endpoint pinned, not environment-derived** (security/correctness audit
finding MEDIUM-1). `openai.OpenAI.__init__()`, when `base_url` is not
supplied, falls back to `os.environ.get("OPENAI_BASE_URL")` before
defaulting to the real OpenAI API (verified by reading the installed SDK
source directly) -- a stray or attacker-influenced `OPENAI_BASE_URL` in
this process's own environment would otherwise silently redirect every
request (carrying the real `OPENAI_API_KEY`) to a different host. `base_url`
is therefore pinned explicitly below to the canonical OpenAI API endpoint,
a vendor-specific literal that belongs only in this one concrete adapter,
never in the generic `LLMProvider` contract. This is not a configurable
endpoint and no environment variable names it -- Phase 26's own approved
scope is exactly one fixed vendor at one fixed address, never an
arbitrary-endpoint mechanism. The SDK's own separate `OPENAI_CUSTOM_HEADERS`
environment override (which can inject arbitrary request headers,
including an `Authorization` override, when present) is not consumed by
anything in this module -- this adapter passes no `default_headers=`, so
the only way that override could apply is the *same* stray-environment-
variable scenario `base_url` pinning above defends against as a class; no
additional code is needed here to not opt into it, since nothing in this
adapter reads or forwards it.

**Existing input bound enforced here too** (security/correctness audit
finding LOW-1). `product/ai/provider.py`'s own module docstring states
"Bounded input/output is enforced here, not left to each tool" -- true of
`FakeLLMProvider.complete()` (rejects `user_content` over
`MAX_USER_CONTENT_CHARS` with `AIValidationError`), and now true of this
adapter too, checked before any request is built, so oversized input never
reaches the OpenAI SDK at all. The real production capability
(`ai.crm.qualify_lead`) cannot trigger this today -- its own `user_content`
is built from bounded CRM columns (`first_name`/`last_name` at 255 chars,
`phone` at 32) -- but the provider contract invariant is preserved
regardless of what a future capability might send.

**Error mapping, one class, differentiated messages.** Every
`openai.*` exception is caught here and re-raised as the existing,
single `product.ai.errors.AIProviderError` -- this repository has never
had more than one provider-failure error type, and this phase does not
introduce one (mirrors `AIProviderError`'s own "never a raw transport/SDK
exception" docstring, and the identical single-error-type precedent
`EmailProviderError` already establishes for SMTP failures). The
message differentiates the cause (authentication, rate limit, invalid
request, timeout, connection, generic status, generic) for operator
debugging and audit-log clarity, but never carries the raw SDK
exception's own body/repr -- "type name and a short reason only"
(`core/email/errors.py::EmailProviderError`'s own convention, reused
here)."""

from __future__ import annotations

import openai
from infra.secrets import get_secrets_provider

from product.ai.errors import AIProviderError, AIProviderNotConfiguredError, AIValidationError
from product.ai.openai_config import get_openai_config
from product.ai.provider import MAX_USER_CONTENT_CHARS, LLMCompletion, clamp_output_chars

#: A bounded, explicit request timeout -- see module docstring's own
#: "No second retry loop" section for why this is set explicitly rather
#: than left at the SDK's own default.
_REQUEST_TIMEOUT_SECONDS = 30.0

#: Exactly one HTTP attempt per `complete()` call -- see module docstring's
#: own "No second retry loop" section.
_SDK_MAX_RETRIES = 0

#: The canonical OpenAI API endpoint, pinned explicitly -- see module
#: docstring's own "Endpoint pinned, not environment-derived" section.
#: A vendor-specific literal, deliberately kept inside this one concrete
#: adapter, never in the generic `LLMProvider` contract.
_OPENAI_API_BASE_URL = "https://api.openai.com/v1"

#: A conservative, approximate characters-per-token ratio used only to
#: size the Responses API's own `max_output_tokens` request parameter
#: from the existing character-based `max_output_chars` bound this
#: module receives -- `clamp_output_chars()` below is what actually
#: enforces the real, authoritative bound on the returned text; this
#: ratio only needs to be generous enough that a real completion is not
#: truncated by the token limit before reaching that character clamp.
_CHARS_PER_TOKEN_ESTIMATE = 4
_MIN_OUTPUT_TOKENS = 16


class OpenAIProvider:
    """A real `LLMProvider` backed by the official OpenAI SDK.
    Constructing an instance resolves configuration/credentials once;
    `complete()` performs one Responses API call per invocation -- no
    persistent conversation state, no retained history (mirrors
    `SmtpEmailProvider`'s own "one short-lived connection per call, no
    pooled/stateful client behavior beyond the SDK's own internal HTTP
    connection pooling" shape)."""

    def __init__(self) -> None:
        config = get_openai_config()
        api_key = get_secrets_provider().get("OPENAI_API_KEY")
        if not api_key:
            raise AIProviderNotConfiguredError(
                "OPENAI_API_KEY is not configured -- no production OpenAI provider can "
                "be built. See product/ai/errors.py::AIProviderNotConfiguredError's own "
                "docstring."
            )
        self._model = config.model
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=_OPENAI_API_BASE_URL,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_SDK_MAX_RETRIES,
        )

    @property
    def name(self) -> str:
        return "openai"

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion:
        if len(user_content) > MAX_USER_CONTENT_CHARS:
            raise AIValidationError(f"user_content exceeds {MAX_USER_CONTENT_CHARS} characters.")
        bounded_chars = clamp_output_chars(max_output_chars)
        max_output_tokens = max(_MIN_OUTPUT_TOKENS, bounded_chars // _CHARS_PER_TOKEN_ESTIMATE)
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=system_prompt,
                input=user_content,
                max_output_tokens=max_output_tokens,
            )
        except openai.AuthenticationError as exc:
            raise AIProviderError(
                "OpenAI rejected the configured credential (authentication failure)."
            ) from exc
        except openai.RateLimitError as exc:
            raise AIProviderError("OpenAI rate limit exceeded.") from exc
        except openai.BadRequestError as exc:
            raise AIProviderError("OpenAI rejected the request as invalid.") from exc
        except openai.APITimeoutError as exc:
            raise AIProviderError("OpenAI request timed out.") from exc
        except openai.APIConnectionError as exc:
            raise AIProviderError("OpenAI could not be reached (connection failure).") from exc
        except openai.APIStatusError as exc:
            raise AIProviderError(
                f"OpenAI returned an error response (status {exc.status_code})."
            ) from exc
        except openai.APIError as exc:
            raise AIProviderError(f"OpenAI request failed: {type(exc).__name__}.") from exc

        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text:
            raise AIProviderError("OpenAI returned an empty or malformed response.")
        return LLMCompletion(text=text[:bounded_chars], provider_name=self.name)


__all__ = ["OpenAIProvider"]
