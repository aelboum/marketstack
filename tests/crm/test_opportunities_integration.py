"""Pipelines/stages/opportunities, stage transitions, and the
`crm.opportunity.stage_changed` event (docs/ROADMAP.md Phase 4.2). Real
disposable Postgres. Marked `integration`, excluded from the default
`pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.agency.provisioning import provision_agency, provision_client
from product.crm.errors import CrmReferenceNotFoundError
from product.crm.opportunities import (
    STAGE_CHANGED_EVENT_TYPE,
    change_stage,
    create_opportunity,
    delete_opportunity,
    get_opportunity,
)
from product.crm.pipelines import create_pipeline, create_stage, list_pipelines, list_stages
from product.foundation.events import subscribe
from product.foundation.values import Money

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = pytest.mark.integration


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


def _default_pipeline_with_stages(owner_id, tenant_id):
    pipeline = create_pipeline(owner_id, tenant_id, name="Sales", is_default=True)
    open_stage = create_stage(owner_id, tenant_id, pipeline.id, name="Open", position=0)
    won_stage = create_stage(owner_id, tenant_id, pipeline.id, name="Won", position=1, is_won=True)
    lost_stage = create_stage(
        owner_id, tenant_id, pipeline.id, name="Lost", position=2, is_lost=True
    )
    return pipeline, open_stage, won_stage, lost_stage


def test_pipeline_and_stage_creation_and_listing() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        pipeline, open_stage, won_stage, lost_stage = _default_pipeline_with_stages(
            owner.id, client.tenant_id
        )
        pipelines = list_pipelines(owner.id, client.tenant_id)
        assert any(p.id == pipeline.id for p in pipelines)
        stages = list_stages(owner.id, client.tenant_id, pipeline.id)
        assert [s.id for s in stages] == [open_stage.id, won_stage.id, lost_stage.id]
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_opportunity_crud_and_amount_round_trip() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        pipeline, open_stage, _won, _lost = _default_pipeline_with_stages(
            owner.id, client.tenant_id
        )
        opportunity = create_opportunity(
            owner.id,
            client.tenant_id,
            name="Big Deal",
            pipeline_id=pipeline.id,
            stage_id=open_stage.id,
            amount=Money.from_decimal("1999.99", "EUR"),
        )
        assert opportunity.amount is not None
        assert opportunity.amount.minor_units == 199999
        assert opportunity.amount.currency == "EUR"

        fetched = get_opportunity(owner.id, client.tenant_id, opportunity.id)
        assert fetched.id == opportunity.id

        delete_opportunity(owner.id, client.tenant_id, opportunity.id)
        with pytest.raises(CrmReferenceNotFoundError):
            get_opportunity(owner.id, client.tenant_id, opportunity.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_opportunity_rejects_stage_from_a_different_pipeline() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        pipeline_a, stage_a, _w, _l = _default_pipeline_with_stages(owner.id, client.tenant_id)
        pipeline_b = create_pipeline(owner.id, client.tenant_id, name="Other Pipeline")
        stage_b = create_stage(
            owner.id, client.tenant_id, pipeline_b.id, name="Only Stage", position=0
        )

        with pytest.raises(CrmReferenceNotFoundError):
            create_opportunity(
                owner.id,
                client.tenant_id,
                name="Mismatched",
                pipeline_id=pipeline_a.id,
                stage_id=stage_b.id,
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_change_stage_publishes_correctly_shaped_event() -> None:
    """docs/ROADMAP.md Phase 4.2's own acceptance criterion: 'each stage
    change is a correctly-shaped published event.'"""
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    received = []

    def _handler(event):
        received.append(event)

    subscribe(STAGE_CHANGED_EVENT_TYPE, _handler)
    try:
        pipeline, open_stage, won_stage, _lost = _default_pipeline_with_stages(
            owner.id, client.tenant_id
        )
        opportunity = create_opportunity(
            owner.id,
            client.tenant_id,
            name="Trackable Deal",
            pipeline_id=pipeline.id,
            stage_id=open_stage.id,
        )
        updated = change_stage(owner.id, client.tenant_id, opportunity.id, won_stage.id)
        assert updated.stage_id == won_stage.id

        assert len(received) == 1
        event = received[0]
        assert event.type == STAGE_CHANGED_EVENT_TYPE
        assert event.version == 1
        assert event.tenant_id == str(client.tenant_id)
        assert event.payload == {
            "opportunity_id": str(opportunity.id),
            "pipeline_id": str(pipeline.id),
            "from_stage_id": str(open_stage.id),
            "to_stage_id": str(won_stage.id),
        }
        # No PII/business-record contents in the payload -- only ids.
        assert "name" not in event.payload
        assert "amount" not in event.payload
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


def test_change_stage_rejects_stage_from_a_different_pipeline() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        pipeline_a, stage_a, _w, _l = _default_pipeline_with_stages(owner.id, client.tenant_id)
        pipeline_b = create_pipeline(owner.id, client.tenant_id, name="Other Pipeline")
        stage_b = create_stage(
            owner.id, client.tenant_id, pipeline_b.id, name="Only Stage", position=0
        )
        opportunity = create_opportunity(
            owner.id, client.tenant_id, name="Deal", pipeline_id=pipeline_a.id, stage_id=stage_a.id
        )
        with pytest.raises(CrmReferenceNotFoundError):
            change_stage(owner.id, client.tenant_id, opportunity.id, stage_b.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
