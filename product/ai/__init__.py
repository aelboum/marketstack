"""This product's own AI Control Plane tool registrations (docs/ROADMAP.md
Phase 9.1-9.3) -- lead qualification, suggested next actions, conversation
summarization, suggested replies, and an AI receptionist advisory tool.
Registers against the installed `saas-os` `control_plane.orchestration
.ToolRegistry` -- never a second agent runtime, never a second Tool
Authorization/Data Authorization/audit mechanism
(docs/RESPONSIBILITY-MATRIX.md).

**Fully consumes `control_plane`, never competes with it**: every tool
here is a `control_plane.orchestration.ToolDefinition`, invoked only
through `product/ai/invocation.py::invoke_product_ai_tool()`, which is a
thin composition of two already-audited SaaS-OS entrypoints
(`control_plane.data_authorization.authorize_data_access()`,
`control_plane.orchestration.invoke_tool()`) -- RBAC/tier enforcement,
Data Authorization (ADR-0013), and audit logging are all `control_plane`'s
own, reused directly. This module never re-implements any of them.

**Depends on `product.crm`, `product.conversations`, and
`product.telephony`** -- see `docs/ADR/0006-ai-depends-on-crm-conversations-telephony.md`
for the full reasoning; each tool wraps exactly one bounded, already-
RBAC-gated read against the module it assists.

**No real LLM or STT/TTS vendor is selected** (`product/ai/provider.py`/
`product/ai/voice_provider.py`'s own module docstrings, mirroring
`product/conversations/sms.py`/`product/telephony/provider.py`'s
identical "no vendor selected" precedent -- `docs/RISKS-AND-OPEN-QUESTIONS.md`
item 6). Every tool factory here takes its provider as an explicit,
required argument with no default.

**No tool built here is registered into
`control_plane.orchestration.default_registry()`** -- the identical
reasoning `product/telephony/__init__.py`'s own module docstring already
gives for mounting no live HTTP route for a provider-dependent write
path: a live-registered tool whose handler can only ever call a Fake
provider would return synthetic output to a real tenant, exactly the
"production-looking fake success" this phase's own instructions forbid.
Every tool factory (`build_<name>_tool(provider) -> ToolDefinition`) is
real, complete, and fully tested against `FakeLLMProvider`/
`FakeSpeechProvider` at the service layer -- exactly what a future real
registration (once a vendor is selected) would call unchanged.

**No persisted tenant AI data policy exists** (`product/ai/policy.py`'s
own module docstring) -- every tool declaring
`requires_data_authorization=True` (all of them; every tool here hands
tenant data to an LLM) is therefore denied by Data Authorization's own
default-deny path for every real tenant today, structurally, not by
omission. This is the honest, disclosed state of the system: no tenant
data can reach an LLM provider through any tool in this codebase until a
later phase adds real, tenant-configurable AI policy.

**No new tables, no new migrations, no new RBAC resources, no new API
routes** -- Phase 9.1's own Scope is "tool definitions only"; every tool
reuses an existing CRM/Conversations/Telephony resource for its RBAC
gate (never a new `ai.*` permission), and `control_plane.orchestration
.ToolRegistry` itself has no database table by design (that module's own
docstring: "a tool is fundamentally code, not data").

**Phase 9.2's human handoff reuses Phase 8's existing routing decision,
never builds a second one** -- see `product/ai/receptionist.py`'s own
module docstring. Phase 8.4 (a dedicated handoff service + UI
notification) remains deferred, unchanged by this phase.
"""
