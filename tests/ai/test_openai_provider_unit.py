"""`product/ai/openai_provider.py` (docs/ROADMAP.md Phase 26). No
database, no network -- the OpenAI SDK client is fully mocked at the
`openai.OpenAI` construction point; nothing here ever contacts the real
OpenAI API. Part of the default `pytest` run.

Mirrors `tests/ai/test_provider_unit.py`'s own shape (construction,
bounded input/output, provider name) for the deterministic `FakeLLMProvider`,
extended with SDK-exception mapping this adapter needs that the Fake
provider never had to handle.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2
import openai
import pytest
from product.ai.errors import AIProviderError, AIProviderNotConfiguredError, AIValidationError
from product.ai.openai_config import get_openai_config
from product.ai.openai_provider import OpenAIProvider
from product.ai.provider import MAX_OUTPUT_CHARS, MAX_USER_CONTENT_CHARS

_FAKE_REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


class _FakeResponse:
    def __init__(self, output_text: object) -> None:
        self.output_text = output_text


@pytest.fixture(autouse=True)
def _configured_environment(monkeypatch: pytest.MonkeyPatch):
    """Every test starts from a fully-configured, fake environment;
    individual tests remove one piece to prove the fail-closed path."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")
    get_openai_config.cache_clear()
    yield
    get_openai_config.cache_clear()


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch):
    """Patches `openai.OpenAI` (as imported inside `openai_provider.py`)
    with a stand-in that records constructor args and every
    `responses.create()` call, and delegates the result to a
    test-supplied callable set via `respond_with()` -- set *before*
    `OpenAIProvider()` is constructed, exactly like every test below
    does."""
    created: list[object] = []
    state: dict[str, Callable[..., object] | None] = {"respond": None}

    class _FakeOpenAIClient:
        def __init__(
            self, *, api_key: str, base_url: str, timeout: float, max_retries: int
        ) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.timeout = timeout
            self.max_retries = max_retries
            self.calls: list[dict[str, object]] = []
            self.responses = self
            created.append(self)

        def create(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            respond = state["respond"]
            assert respond is not None, "call fake_client.respond_with(...) before completing"
            return respond(**kwargs)

    monkeypatch.setattr("product.ai.openai_provider.openai.OpenAI", _FakeOpenAIClient)

    class _Handle:
        @staticmethod
        def respond_with(fn) -> None:
            state["respond"] = fn

        @property
        def client(self):
            return created[-1]

    return _Handle()


# --- Construction -------------------------------------------------------


def test_provider_name_is_openai(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    assert provider.name == "openai"


def test_model_configuration_is_read_from_environment(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    assert fake_client.client.calls[0]["model"] == "gpt-test-model"


def test_secret_is_obtained_through_infra_secrets(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    OpenAIProvider()
    assert fake_client.client.api_key == "sk-test-not-a-real-key"


def test_missing_model_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    get_openai_config.cache_clear()
    with pytest.raises(AIProviderNotConfiguredError):
        OpenAIProvider()


def test_missing_api_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AIProviderNotConfiguredError):
        OpenAIProvider()


# --- Endpoint pinning (security/correctness audit MEDIUM-1) -----------------


def test_endpoint_is_pinned_to_the_canonical_openai_api(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    assert fake_client.client.base_url == "https://api.openai.com/v1"


def test_openai_base_url_environment_override_cannot_redirect_the_provider(
    fake_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed OpenAI SDK falls back to `OPENAI_BASE_URL` when
    `base_url` is not explicitly supplied (verified by reading
    `openai._client.OpenAI.__init__` directly) -- proves this adapter's
    own explicit `base_url=` pin means that environment variable has no
    effect on the endpoint actually used, however it is set."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://attacker.example.invalid/v1")
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    assert fake_client.client.base_url == "https://api.openai.com/v1"


def test_construction_never_passes_default_headers(
    fake_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the security property that actually matters for
    `OPENAI_CUSTOM_HEADERS` (the installed SDK's own separate environment
    override, which can inject arbitrary request headers when
    `default_headers=` is not otherwise pinned): this adapter's own
    construction call never passes `default_headers` at all -- the fake
    client's constructor signature below accepts only the exact four
    keyword arguments the real adapter is expected to pass, so an
    unexpected fifth argument (such as a `default_headers=` this adapter
    started deriving from the environment) would raise `TypeError` here,
    failing this test, regardless of whether `OPENAI_CUSTOM_HEADERS` is
    set in the process environment."""
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "Authorization: Bearer attacker-supplied-value")
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    OpenAIProvider()  # would raise TypeError if the constructor call shape changed


# --- SDK retries disabled (security/correctness audit MEDIUM-2) -------------


def test_sdk_retries_are_disabled(fake_client) -> None:
    """The OpenAI SDK defaults to `max_retries=2` (up to three HTTP
    attempts inside one `complete()` call) -- proves this adapter pins
    `max_retries=0` instead, so the durable workflow's own `RetryPolicy`
    remains the sole retry owner."""
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    assert fake_client.client.max_retries == 0


# --- User-content bound (security/correctness audit LOW-1) ------------------


def test_user_content_at_the_bound_is_accepted(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    content_at_bound = "x" * MAX_USER_CONTENT_CHARS
    completion = provider.complete(
        system_prompt="sys", user_content=content_at_bound, max_output_chars=100
    )
    assert completion.text == "ok"
    assert fake_client.client.calls[0]["input"] == content_at_bound


def test_user_content_over_the_bound_is_rejected(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    oversized_content = "x" * (MAX_USER_CONTENT_CHARS + 1)
    with pytest.raises(AIValidationError):
        provider.complete(system_prompt="sys", user_content=oversized_content, max_output_chars=100)


def test_oversized_user_content_never_reaches_the_openai_sdk(fake_client) -> None:
    def _fail_if_called(**_: object) -> object:
        raise AssertionError("the OpenAI SDK must never be called for oversized user_content")

    fake_client.respond_with(_fail_if_called)
    provider = OpenAIProvider()
    oversized_content = "x" * (MAX_USER_CONTENT_CHARS + 1)
    with pytest.raises(AIValidationError):
        provider.complete(system_prompt="sys", user_content=oversized_content, max_output_chars=100)
    assert fake_client.client.calls == []


# --- Request mapping ------------------------------------------------------


def test_system_prompt_and_user_content_are_mapped_correctly(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(
        system_prompt="You are a sales assistant.", user_content="Name: Jane", max_output_chars=100
    )
    call = fake_client.client.calls[0]
    assert call["instructions"] == "You are a sales assistant."
    assert call["input"] == "Name: Jane"


def test_no_tenant_specific_fields_are_sent(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    call = fake_client.client.calls[0]
    assert set(call.keys()) == {"model", "instructions", "input", "max_output_tokens"}


def test_bounded_output_parameter_is_applied(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("ok"))
    provider = OpenAIProvider()
    provider.complete(system_prompt="sys", user_content="hi", max_output_chars=400)
    call = fake_client.client.calls[0]
    assert isinstance(call["max_output_tokens"], int)
    assert call["max_output_tokens"] > 0


# --- Successful response ---------------------------------------------------


def test_successful_response_maps_to_llm_completion(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse("A qualified lead note."))
    provider = OpenAIProvider()
    completion = provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    assert completion.text == "A qualified lead note."
    assert completion.provider_name == "openai"


# --- Output validation ------------------------------------------------------


def test_empty_response_text_fails_safely(fake_client) -> None:
    fake_client.respond_with(lambda **_: _FakeResponse(""))
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_missing_output_text_attribute_fails_safely(fake_client) -> None:
    fake_client.respond_with(lambda **_: object())
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_output_is_truncated_to_the_existing_repository_bound(fake_client) -> None:
    long_text = "x" * (MAX_OUTPUT_CHARS + 500)
    fake_client.respond_with(lambda **_: _FakeResponse(long_text))
    provider = OpenAIProvider()
    completion = provider.complete(
        system_prompt="sys", user_content="hi", max_output_chars=MAX_OUTPUT_CHARS + 500
    )
    assert len(completion.text) <= MAX_OUTPUT_CHARS


# --- Errors ------------------------------------------------------------


def _status_error(cls: type, status_code: int) -> Exception:
    response = httpx2.Response(status_code, request=_FAKE_REQUEST)
    return cls(f"{cls.__name__} for test", response=response, body=None)


def test_authentication_failure_maps_to_provider_error(fake_client) -> None:
    def _raise(**_: object):
        raise _status_error(openai.AuthenticationError, 401)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_invalid_request_maps_to_provider_error(fake_client) -> None:
    def _raise(**_: object):
        raise _status_error(openai.BadRequestError, 400)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_rate_limit_maps_to_provider_error(fake_client) -> None:
    def _raise(**_: object):
        raise _status_error(openai.RateLimitError, 429)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_timeout_maps_to_provider_error(fake_client) -> None:
    def _raise(**_: object):
        raise openai.APITimeoutError(request=_FAKE_REQUEST)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_connection_failure_maps_to_provider_error(fake_client) -> None:
    def _raise(**_: object):
        raise openai.APIConnectionError(request=_FAKE_REQUEST)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_server_error_maps_to_provider_error(fake_client) -> None:
    def _raise(**_: object):
        raise _status_error(openai.InternalServerError, 500)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)


def test_no_raw_sdk_exception_ever_escapes(fake_client) -> None:
    """Every mapped error is the application's own `AIProviderError` --
    never the raw `openai.*` exception itself."""

    def _raise(**_: object):
        raise _status_error(openai.AuthenticationError, 401)

    fake_client.respond_with(_raise)
    provider = OpenAIProvider()
    try:
        provider.complete(system_prompt="sys", user_content="hi", max_output_chars=100)
    except openai.AuthenticationError:
        pytest.fail("raw openai.AuthenticationError leaked through the provider boundary")
    except AIProviderError:
        pass
