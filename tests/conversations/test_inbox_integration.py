"""The Unified Inbox read model (docs/ROADMAP.md Phase 30) --
`product/conversations/inbox.py`. Real disposable Postgres. Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from core.identity import add_tenant_membership
from core.identity.sessions import issue_session
from core.rbac import RoleScope, assign_role
from fastapi.testclient import TestClient
from product.agency.provisioning import provision_agency, provision_client
from product.agency.roles import ensure_client_member_role
from product.api.main import create_app
from product.conversations.errors import ConversationAccessDeniedError
from product.conversations.inbox import count_needs_reply, list_inbox
from product.conversations.messages import create_message
from product.conversations.models import DIRECTION_INBOUND, DIRECTION_OUTBOUND
from product.conversations.threads import assign_thread, create_thread
from product.crm.contacts import create_contact

from tests.conversations._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _auth_headers(user_id) -> dict[str, str]:
    _session, raw_token = issue_session(user_id)
    return {"Authorization": f"Bearer {raw_token}"}


def _contact(owner_id, tenant_id):
    return create_contact(owner_id, tenant_id, first_name="Jamie", last_name="Vos")


def _thread_with_last_message(owner_id, tenant_id, contact_id, *, direction, body="hi"):
    thread = create_thread(owner_id, tenant_id, contact_id=contact_id, channel="email")
    create_message(
        owner_id,
        tenant_id,
        thread.id,
        direction=direction,
        is_internal_note=False,
        body=body,
        author_user_id=owner_id,
    )
    return thread


def test_list_inbox_orders_by_recency_and_attaches_latest_message() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact(owner.id, client.tenant_id)
        older = _thread_with_last_message(
            owner.id, client.tenant_id, contact.id, direction=DIRECTION_OUTBOUND, body="first"
        )
        newer = _thread_with_last_message(
            owner.id,
            client.tenant_id,
            contact.id,
            direction=DIRECTION_INBOUND,
            body="second thread",
        )

        items = list_inbox(owner.id, client.tenant_id)

        assert [item.thread_id for item in items] == [newer.id, older.id]
        assert items[0].last_message_preview == "second thread"
        assert items[0].last_message_direction == DIRECTION_INBOUND
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_needs_reply_is_derived_from_latest_message_direction_only() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact(owner.id, client.tenant_id)
        awaiting = _thread_with_last_message(
            owner.id, client.tenant_id, contact.id, direction=DIRECTION_INBOUND
        )
        answered = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
        create_message(
            owner.id,
            client.tenant_id,
            answered.id,
            direction=DIRECTION_INBOUND,
            is_internal_note=False,
            body="customer asked",
            author_user_id=owner.id,
        )
        create_message(
            owner.id,
            client.tenant_id,
            answered.id,
            direction=DIRECTION_OUTBOUND,
            is_internal_note=False,
            body="staff replied",
            author_user_id=owner.id,
        )
        empty_thread = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="email"
        )

        items = {item.thread_id: item for item in list_inbox(owner.id, client.tenant_id)}

        assert items[awaiting.id].needs_reply is True
        assert items[answered.id].needs_reply is False
        assert items[empty_thread.id].needs_reply is False
        assert items[empty_thread.id].last_message_preview is None
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_needs_reply_filter_returns_only_matching_threads() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact(owner.id, client.tenant_id)
        awaiting = _thread_with_last_message(
            owner.id, client.tenant_id, contact.id, direction=DIRECTION_INBOUND
        )
        _thread_with_last_message(
            owner.id, client.tenant_id, contact.id, direction=DIRECTION_OUTBOUND
        )

        items = list_inbox(owner.id, client.tenant_id, needs_reply=True)

        assert [item.thread_id for item in items] == [awaiting.id]

        count = count_needs_reply(owner.id, client.tenant_id)
        assert count == 1
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_assigned_filters_only_expose_real_assignment_data() -> None:
    # `assign_thread()`'s own IDOR check requires a real `TenantMembership`
    # *at the client tenant* -- an agency owner reaching this tenant only
    # via inherited SUBTREE role (never a direct membership row here,
    # `tests/conversations/test_messages_and_notes_integration.py
    # ::test_assign_thread_to_real_member_succeeds`'s own precedent)
    # cannot be the assignee. `member` is a real client-tenant member for
    # exactly this reason -- both the assignee and the actor proving
    # "assigned to me" from their own point of view.
    owner = make_user()
    member = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact(owner.id, client.tenant_id)
        membership = add_tenant_membership(client.tenant_id, member.id)
        member_role = ensure_client_member_role(client.tenant_id)
        assign_role(
            client.tenant_id,
            membership.id,
            member_role.id,
            scope=RoleScope.SELF,
            actor_user_id=owner.id,
        )

        mine = create_thread(owner.id, client.tenant_id, contact_id=contact.id, channel="email")
        assign_thread(owner.id, client.tenant_id, mine.id, member.id)
        unassigned = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="email"
        )

        mine_items = list_inbox(member.id, client.tenant_id, assigned="me")
        assert [item.thread_id for item in mine_items] == [mine.id]

        unassigned_items = list_inbox(owner.id, client.tenant_id, assigned="unassigned")
        assert [item.thread_id for item in unassigned_items] == [unassigned.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, member.id)


def test_channel_filter() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact(owner.id, client.tenant_id)
        email_thread = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="email"
        )
        chat_thread = create_thread(
            owner.id, client.tenant_id, contact_id=contact.id, channel="chat"
        )

        items = list_inbox(owner.id, client.tenant_id, channel="chat")

        assert [item.thread_id for item in items] == [chat_thread.id]
        assert email_thread.id not in [item.thread_id for item in items]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_list_inbox_is_tenant_isolated() -> None:
    owner = make_user()
    agency_a, client_a = _agency_and_client(owner.id)
    agency_b, client_b = _agency_and_client(owner.id)
    try:
        contact_a = _contact(owner.id, client_a.tenant_id)
        contact_b = _contact(owner.id, client_b.tenant_id)
        thread_a = create_thread(
            owner.id, client_a.tenant_id, contact_id=contact_a.id, channel="email"
        )
        create_thread(owner.id, client_b.tenant_id, contact_id=contact_b.id, channel="email")

        items = list_inbox(owner.id, client_a.tenant_id)

        assert [item.thread_id for item in items] == [thread_a.id]
    finally:
        cleanup_tenant_tree(client_a.tenant_id, agency_a.tenant_id)
        cleanup_tenant_tree(client_b.tenant_id, agency_b.tenant_id)
        cleanup_users(owner.id)


def test_list_inbox_denies_unauthorized_actor() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        with pytest.raises(ConversationAccessDeniedError):
            list_inbox(stranger.id, client.tenant_id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


def test_http_list_inbox_returns_real_data() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        contact = _contact(owner.id, client.tenant_id)
        thread = _thread_with_last_message(
            owner.id, client.tenant_id, contact.id, direction=DIRECTION_INBOUND, body="hallo daar"
        )

        app = create_app()
        http_client = TestClient(app)
        response = http_client.get(
            f"/v1/conversations/tenants/{client.tenant_id}/inbox",
            headers=_auth_headers(owner.id),
        )

        assert response.status_code == 200
        body = response.json()
        assert body[0]["thread_id"] == str(thread.id)
        assert body[0]["needs_reply"] is True
        assert body[0]["last_message_preview"] == "hallo daar"
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_http_invalid_assigned_filter_is_a_400() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        app = create_app()
        http_client = TestClient(app)
        response = http_client.get(
            f"/v1/conversations/tenants/{client.tenant_id}/inbox",
            headers=_auth_headers(owner.id),
            params={"assigned": "everyone"},
        )
        assert response.status_code == 400
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_http_cross_tenant_inbox_is_non_enumerating_404() -> None:
    owner = make_user()
    stranger = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        app = create_app()
        http_client = TestClient(app)
        response = http_client.get(
            f"/v1/conversations/tenants/{client.tenant_id}/inbox",
            headers=_auth_headers(stranger.id),
        )
        assert response.status_code == 404
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)
