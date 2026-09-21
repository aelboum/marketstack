"""The `ReviewProvider` interface (docs/ROADMAP.md Phase 12.2) --
mirrors `core/email/provider.py::EmailProvider`'s exact shape (a
`@runtime_checkable Protocol` plus one in-memory `Fake*` implementation of
the identical interface).

**Phase 12.2 is deliberately deferred, not implemented, in this phase.**
The roadmap names Google Business Profile/Facebook "as prioritized," but
no vendor has actually been chosen (mirrors `docs/ROADMAP.md` Phase 9.4's
own "no vendor is chosen here, and none is implied" treatment of the
LLM/voice provider question, `docs/RISKS-AND-OPEN-QUESTIONS.md` item 6).
Building a real adapter now would mean either inventing credentials that
do not exist or silently picking a vendor the roadmap does not commit to
-- both explicitly out of scope
("do not add credentials or real external provider integrations merely to
demonstrate the architecture," "do not silently choose a vendor if the
roadmap does not specify one").

What this phase *does* establish: the provider-neutral boundary itself
(`ReviewProvider`), so that whichever adapter is built later plugs into an
already-reviewed contract rather than requiring the domain model or
service layer to change shape around it. `resolve_provider()` returns
`None` for every provider name today, by design -- mirrors
`product.ai.policy.resolve_tenant_ai_policy()`'s own "returns `None` for
every tenant by design" precedent (docs/ROADMAP.md Phase 9's own
9.1-9.3 module docstring) for the identical reason: a deliberate,
documented default-deny/absent posture, not a gap.

`FakeReviewProvider` is what this module's own tests inject directly
(as a constructor parameter, mirroring `product/conversations
/email_sending.py::send_email_message()`'s own `provider: EmailProvider |
None = None` parameter) -- never through `resolve_provider()`, which a
test must not need to monkeypatch to exercise the response-posting code
path. It is not, and must never be presented as, a production
integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ReviewProviderPostResult:
    """The one normalized outcome every `ReviewProvider` implementation
    returns -- never a provider-specific response object, mirroring
    `core.email.provider.EmailSendResult`'s identical role."""

    accepted: bool
    provider_response_id: str | None = None


@runtime_checkable
class ReviewProvider(Protocol):
    """The one provider-side operation this phase's domain model needs:
    posting a response to an already-imported external review. Fetching/
    syncing reviews from a real provider is Phase 12.2's own future scope,
    not part of this Protocol yet -- this phase has no adapter that
    imports reviews automatically (`product/reputation/reviews.py
    ::record_review()` is a manual, authenticated write only)."""

    name: str

    def post_response(self, *, external_review_id: str, body: str) -> ReviewProviderPostResult:
        """Post `body` as a response to the review identified by
        `external_review_id` at this provider. Must raise a provider-
        specific error (never propagate a raw transport exception) on
        failure -- out of scope to define further until a real adapter
        exists."""
        ...


class FakeReviewProvider:
    """An in-memory `ReviewProvider` -- no network access, no credentials.
    Records every response it was asked to post so tests can assert
    against it directly, mirroring `core.email.provider.FakeEmailProvider`'s
    identical role. Test-only; never wired as a production default."""

    def __init__(self, *, name: str = "fake", fail: bool = False) -> None:
        self.name = name
        self._fail = fail
        self.posted: list[tuple[str, str]] = []

    def post_response(self, *, external_review_id: str, body: str) -> ReviewProviderPostResult:
        if self._fail:
            return ReviewProviderPostResult(accepted=False)
        self.posted.append((external_review_id, body))
        return ReviewProviderPostResult(accepted=True, provider_response_id=external_review_id)


def resolve_provider(provider: str) -> ReviewProvider | None:
    """Returns the configured `ReviewProvider` for `provider`, or `None`
    if none is configured -- `None` for every provider name today, by
    design (module docstring). A real production registry, once Phase
    12.2 selects a vendor, replaces this function's body only -- callers
    (`product/reputation/responses.py::create_response()`) already handle
    the `None` case correctly."""
    return None


__all__ = [
    "FakeReviewProvider",
    "ReviewProvider",
    "ReviewProviderPostResult",
    "resolve_provider",
]
