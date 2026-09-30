"""The Twilio `TelephonyProvider` adapter (docs/ROADMAP.md Phase 27.0 --
"Twilio Telephony Foundation"). The one concrete implementation of
`product/telephony/provider.py::TelephonyProvider` this phase adds, behind
the existing provider-neutral boundary -- mirrors
`product/ai/openai_provider.py::OpenAIProvider`'s own "only the concrete
adapter knows the vendor's specific shape" precedent exactly.

**No new SDK dependency.** This module calls Twilio's REST API directly
via `httpx` (already a repository dependency) rather than adding the
`twilio` PyPI package -- the smallest adapter this phase's own "smallest
adapter implementing the existing TelephonyProvider abstraction"
instruction calls for, and it avoids introducing a second HTTP client
library alongside `httpx`'s own existing use elsewhere in this repository.
Twilio's REST API is a plain, documented HTTP/form-encoded API; nothing
here requires the SDK's own convenience wrappers.

**Credentials.** `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` are read once, at
construction time, through `infra.secrets.get_secrets_provider()` -- never
`os.environ` directly, never logged, never included in any exception this
module raises (mirrors `OpenAIProvider`'s identical discipline). Missing
configuration raises `TelephonyProviderNotConfiguredError`.

**Attended transfer is composed, not native** (this phase's own prior
architecture research: Twilio's Voice API has no atomic warm-transfer
primitive). The consultation leg and the original caller leg are both
directed, via TwiML, into the same named `<Conference>` -- the exact
Twilio-documented pattern (`docs.twilio.com/voice/tutorials/warm-transfer`):
create a consultation leg that joins conference `transfer-{CallSid}`
(`create_consultation_leg()`), then redirect the *original* live call into
that same conference via Twilio's "Update a Call" (Modify Live Calls) REST
operation (`bridge_call()`). Redirecting the original call's own live
TwiML is also what ends the AI's own handling of it -- see
`product/telephony/provider.py`'s own "Remove AI leg is deliberately not a
separate method" reasoning; there is no separate "AI leg" `CallSid` for
this adapter to remove.

**Bounded transfer timeout without a Marketstack-owned timer.** The
consultation leg is created with Twilio's own `Timeout` call-creation
parameter (`_CONSULTATION_RING_TIMEOUT_SECONDS`) -- Twilio itself declares
the leg `no-answer` after that many seconds and delivers the corresponding
status-callback event; this phase never runs its own scheduler/retry loop
to enforce the bound (mirrors `OpenAIProvider`'s own "no second retry
loop" precedent, applied here to timeout instead of retries).

**Webhook signature verification follows Twilio's actual, documented
algorithm** (`docs.twilio.com/usage/security#validating-requests`):
HMAC-SHA1 over the exact request URL with every POST parameter, sorted by
key, appended as `key+value` with no delimiter; the result is
base64-encoded and compared to the `X-Twilio-Signature` header in constant
time. This is why `product/telephony/provider.py::TelephonyProvider
.verify_webhook_signature()` carries a `url` parameter -- Twilio's scheme,
unlike `FakeTelephonyProvider`'s own HMAC-SHA256-over-body-only scheme,
fundamentally requires the URL."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode

import httpx
from infra.secrets import get_secrets_provider

from product.telephony.adapters.twilio_config import get_twilio_config
from product.telephony.errors import TelephonyProviderError, TelephonyProviderNotConfiguredError
from product.telephony.provider import ConsultationLeg, PlacedCall, ProvisionedNumber

#: The canonical Twilio REST API base, pinned explicitly -- mirrors
#: `OpenAIProvider`'s own "Endpoint pinned, not environment-derived"
#: discipline for the identical reason: a stray environment variable must
#: never be able to redirect a request carrying the real Auth Token.
_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

_REQUEST_TIMEOUT_SECONDS = 15.0

#: How long Twilio rings the human destination before declaring the
#: consultation leg `no-answer` -- see module docstring's own "Bounded
#: transfer timeout" section. Not (yet) a tenant-configurable value; this
#: phase ships one platform-wide bound, the smallest correct choice for
#: an initial single-provider, single-market launch.
_CONSULTATION_RING_TIMEOUT_SECONDS = 20

_TRANSFER_STATUS_CALLBACK_EVENTS = ("answered", "completed", "busy", "no-answer", "failed")

_INBOUND_WEBHOOK_PATH = "/v1/telephony/adapters/twilio/inbound-call"
_TRANSFER_WEBHOOK_PATH = "/v1/telephony/adapters/twilio/transfer-events"


def _twilio_signature(auth_token: str, url: str, body: bytes) -> str:
    """Twilio's own documented HMAC-SHA1 construction -- see module
    docstring. `body` is the raw, unparsed form-encoded request body;
    non-form (empty/JSON) bodies contribute no parameters, matching
    Twilio's own behavior for a GET-style validation."""
    pairs = sorted(parse_qsl(body.decode("utf-8"), keep_blank_values=True), key=lambda kv: kv[0])
    data = url + "".join(key + value for key, value in pairs)
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _conference_name(original_provider_call_id: str) -> str:
    return f"transfer-{original_provider_call_id}"


def _conference_twiml(conference_name: str, *, start_on_enter: bool) -> str:
    """The one, small TwiML shape this adapter ever generates -- both the
    consultation leg and (via `bridge_call()`'s own redirect) the original
    caller leg join the identical named conference. Never exposed outside
    this module -- see `product/telephony/provider.py`'s own "no TwiML
    outside the adapter boundary" requirement."""
    start_attr = "true" if start_on_enter else "false"
    return (
        "<Response><Dial>"
        f'<Conference startConferenceOnEnter="{start_attr}" endConferenceOnExit="true">'
        f"{conference_name}</Conference></Dial></Response>"
    )


class TwilioTelephonyProvider:
    """A real `TelephonyProvider` backed by Twilio's REST API. One
    instance holds one platform credential and one platform-configured
    callback base URL; it never receives, stores, or reasons about
    tenant-specific configuration beyond the plain `from_number`/
    `to_number`/destination strings every `TelephonyProvider` method
    already takes."""

    def __init__(self, *, _transport: httpx.BaseTransport | None = None) -> None:
        """`_transport` is a private, test-only seam (an `httpx.MockTransport`)
        -- never set in production, where `None` yields `httpx.Client`'s own
        real network transport. Mirrors the same "no production behavior
        change, one seam for a deterministic test double" shape
        `product/telephony/provider.py::FakeTelephonyProvider` gives every
        other telephony test, applied here since mocking Twilio's REST API
        itself (rather than swapping the whole provider) is what proves
        this adapter's own request-building/response-parsing logic."""
        config = get_twilio_config()
        secrets = get_secrets_provider()
        account_sid = secrets.get("TWILIO_ACCOUNT_SID")
        auth_token = secrets.get("TWILIO_AUTH_TOKEN")
        if not account_sid or not auth_token:
            raise TelephonyProviderNotConfiguredError(
                "TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN are not configured -- no production "
                "Twilio provider can be built."
            )
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._callback_base_url = config.voice_callback_base_url
        self._client = httpx.Client(
            base_url=f"{_TWILIO_API_BASE}/Accounts/{account_sid}",
            auth=(account_sid, auth_token),
            timeout=_REQUEST_TIMEOUT_SECONDS,
            transport=_transport,
        )

    @property
    def name(self) -> str:
        return "twilio"

    def _inbound_webhook_url(self) -> str:
        return f"{self._callback_base_url}{_INBOUND_WEBHOOK_PATH}"

    def _transfer_webhook_url(
        self, *, tenant_id: str, original_provider_call_id: str, attempt_id: str
    ) -> str:
        # `attempt_id` (Phase 27.0 HIGH-1 remediation) is embedded here for
        # the identical reason `tenant_id` already is: Twilio echoes this
        # exact URL back on every status-callback delivery, and Twilio's
        # own signature covers the exact URL string, so an attacker cannot
        # substitute a different attempt id without invalidating the
        # signature. This is what lets `transfer_events_webhook()` reject a
        # callback belonging to an older, already-superseded transfer
        # attempt as stale.
        return (
            f"{self._callback_base_url}{_TRANSFER_WEBHOOK_PATH}"
            f"/{tenant_id}/{original_provider_call_id}/{attempt_id}"
        )

    def _post(self, path: str, *, data: list[tuple[str, str]]) -> dict[str, object]:
        # `httpx`'s own `data=` parameter only form-encodes a `Mapping` --
        # a plain list of tuples (needed here for Twilio's repeated
        # `StatusCallbackEvent` field) is otherwise misread as raw request
        # content. Encoded explicitly instead, mirroring exactly what
        # `httpx` itself would produce for a `Mapping`.
        body = urlencode(data).encode("utf-8")
        try:
            response = self._client.post(
                f"{path}.json",
                content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TelephonyProviderError(
                f"Twilio returned an error response (status {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            raise TelephonyProviderError(f"Twilio request failed: {type(exc).__name__}.") from exc
        return response.json()

    def _get(self, path: str) -> dict[str, object]:
        try:
            response = self._client.get(f"{path}.json")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TelephonyProviderError(
                f"Twilio returned an error response (status {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            raise TelephonyProviderError(f"Twilio request failed: {type(exc).__name__}.") from exc
        return response.json()

    def provision_number(self, *, country_code: str) -> ProvisionedNumber:
        available = self._get(f"/AvailablePhoneNumbers/{country_code}/Local")
        candidates = available.get("available_phone_numbers")
        if not isinstance(candidates, list) or not candidates:
            raise TelephonyProviderError(
                f"Twilio has no available local numbers for country {country_code!r}."
            )
        first = candidates[0]
        if not isinstance(first, dict) or not isinstance(first.get("phone_number"), str):
            raise TelephonyProviderError("Twilio returned a malformed available-number result.")
        chosen_number = first["phone_number"]

        purchased = self._post(
            "/IncomingPhoneNumbers",
            data=[
                ("PhoneNumber", chosen_number),
                ("VoiceUrl", self._inbound_webhook_url()),
                ("VoiceMethod", "POST"),
            ],
        )
        sid = purchased.get("sid")
        if not isinstance(sid, str):
            raise TelephonyProviderError("Twilio returned a malformed IncomingPhoneNumber result.")
        return ProvisionedNumber(phone_number=chosen_number, provider_number_id=sid)

    def place_call(self, *, from_number: str, to_number: str) -> PlacedCall:
        created = self._post(
            "/Calls",
            data=[
                ("From", from_number),
                ("To", to_number),
                ("Url", self._inbound_webhook_url()),
                ("Method", "POST"),
            ],
        )
        sid = created.get("sid")
        if not isinstance(sid, str):
            raise TelephonyProviderError("Twilio returned a malformed Call result.")
        return PlacedCall(provider_call_id=sid)

    def verify_webhook_signature(
        self, *, headers: Mapping[str, str], body: bytes, path: str = ""
    ) -> bool:
        # Phase 27.0 HIGH-2 remediation: the URL verified against is built
        # here, from this adapter's OWN already-trusted
        # `_callback_base_url` (platform configuration, never derived from
        # the inbound request) plus `path` (the request's own path+query,
        # which the caller reads directly off the ASGI request -- never a
        # forwarded-header-derived scheme/host). This is deliberately the
        # ONLY URL ever tried -- no candidate list, no opportunistic
        # fallback to `request.url` -- so a request that reaches this
        # process by any route (through the real reverse proxy, or by
        # hitting the backend's own directly-published port) is verified
        # against the identical, single, correct external URL Twilio
        # itself signed against, regardless of how this request actually
        # arrived. Forged `Host`/`X-Forwarded-*` headers on the inbound
        # request have no effect whatsoever, because they are never read
        # here.
        provided = next(
            (value for key, value in headers.items() if key.lower() == "x-twilio-signature"),
            None,
        )
        if not provided or not path:
            return False
        url = f"{self._callback_base_url}{path}"
        expected = _twilio_signature(self._auth_token, url, body)
        return hmac.compare_digest(provided, expected)

    def create_consultation_leg(
        self,
        *,
        original_provider_call_id: str,
        human_destination: str,
        tenant_id: str,
        attempt_id: str,
    ) -> ConsultationLeg:
        original = self._get(f"/Calls/{original_provider_call_id}")
        caller_id = original.get("to")
        if not isinstance(caller_id, str) or not caller_id:
            raise TelephonyProviderError(
                f"could not resolve caller id for call {original_provider_call_id!r}."
            )
        conference = _conference_name(original_provider_call_id)
        status_callback = self._transfer_webhook_url(
            tenant_id=tenant_id,
            original_provider_call_id=original_provider_call_id,
            attempt_id=attempt_id,
        )
        created = self._post(
            "/Calls",
            data=[
                ("From", caller_id),
                ("To", human_destination),
                ("Twiml", _conference_twiml(conference, start_on_enter=False)),
                ("Timeout", str(_CONSULTATION_RING_TIMEOUT_SECONDS)),
                ("StatusCallback", status_callback),
                ("StatusCallbackMethod", "POST"),
                *[("StatusCallbackEvent", event) for event in _TRANSFER_STATUS_CALLBACK_EVENTS],
            ],
        )
        sid = created.get("sid")
        if not isinstance(sid, str):
            raise TelephonyProviderError("Twilio returned a malformed consultation Call result.")
        return ConsultationLeg(provider_leg_id=sid)

    def bridge_call(
        self, *, original_provider_call_id: str, consultation_leg: ConsultationLeg
    ) -> None:
        conference = _conference_name(original_provider_call_id)
        self._post(
            f"/Calls/{original_provider_call_id}",
            data=[("Twiml", _conference_twiml(conference, start_on_enter=True))],
        )


__all__ = ["TwilioTelephonyProvider"]
