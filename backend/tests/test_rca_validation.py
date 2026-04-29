from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import RCAIn, WorkItem, WorkItemStatus
from app.workflow import InvalidTransition, StateMachine


def make_item(status: WorkItemStatus = WorkItemStatus.RESOLVED) -> WorkItem:
    now = datetime.now(timezone.utc)
    return WorkItem(
        id="wi-1",
        component_id="RDBMS_PRIMARY",
        component_type="RDBMS",
        service="orders",
        severity="P0",
        status=status,
        signal_count=4,
        first_signal_at=now,
        last_signal_at=now,
        created_at=now,
        updated_at=now,
    )


def test_rca_rejects_incomplete_text_fields() -> None:
    with pytest.raises(ValidationError):
        RCAIn(
            incident_start=datetime.now(timezone.utc),
            incident_end=datetime.now(timezone.utc),
            root_cause_category="DB",
            fix_applied="short",
            prevention_steps="also short",
        )


def test_rca_rejects_negative_mttr_window() -> None:
    with pytest.raises(ValidationError):
        RCAIn(
            incident_start=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            incident_end=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
            root_cause_category="Database failover",
            fix_applied="Promoted a healthy replica and replayed the WAL backlog.",
            prevention_steps="Add failover runbooks and synthetic replica lag alerts.",
        )


def test_rca_rejects_future_incident_end() -> None:
    with pytest.raises(ValidationError):
        RCAIn(
            incident_start=datetime.now(timezone.utc),
            incident_end=datetime.now(timezone.utc) + timedelta(minutes=5),
            root_cause_category="Database failover",
            fix_applied="Promoted a healthy replica and replayed the WAL backlog.",
            prevention_steps="Add failover runbooks and synthetic replica lag alerts.",
        )


def test_closed_transition_requires_rca() -> None:
    machine = StateMachine()
    with pytest.raises(InvalidTransition, match="RCA is mandatory"):
        machine.validate(make_item(), WorkItemStatus.CLOSED, None)


def test_workflow_is_forward_only() -> None:
    machine = StateMachine()

    machine.validate(make_item(WorkItemStatus.OPEN), WorkItemStatus.INVESTIGATING, None)
    machine.validate(make_item(WorkItemStatus.INVESTIGATING), WorkItemStatus.RESOLVED, None)

    with pytest.raises(InvalidTransition):
        machine.validate(make_item(WorkItemStatus.RESOLVED), WorkItemStatus.INVESTIGATING, None)

    with pytest.raises(InvalidTransition):
        machine.validate(make_item(WorkItemStatus.OPEN), WorkItemStatus.RESOLVED, None)
