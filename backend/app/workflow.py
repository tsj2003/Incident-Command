from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import RCARecord, WorkItem, WorkItemStatus


class InvalidTransition(ValueError):
    pass


class IncidentState(ABC):
    """Base state object used by the workflow State pattern."""

    status: WorkItemStatus

    @abstractmethod
    def can_transition_to(self, target: WorkItemStatus) -> bool:
        raise NotImplementedError

    def validate_transition(self, target: WorkItemStatus, rca: RCARecord | None) -> None:
        if not self.can_transition_to(target):
            raise InvalidTransition(f"cannot transition from {self.status} to {target}")
        if target == WorkItemStatus.CLOSED and rca is None:
            raise InvalidTransition("RCA is mandatory before closing an incident")


class OpenState(IncidentState):
    status = WorkItemStatus.OPEN

    def can_transition_to(self, target: WorkItemStatus) -> bool:
        return target == WorkItemStatus.INVESTIGATING


class InvestigatingState(IncidentState):
    status = WorkItemStatus.INVESTIGATING

    def can_transition_to(self, target: WorkItemStatus) -> bool:
        return target == WorkItemStatus.RESOLVED


class ResolvedState(IncidentState):
    status = WorkItemStatus.RESOLVED

    def can_transition_to(self, target: WorkItemStatus) -> bool:
        return target == WorkItemStatus.CLOSED


class ClosedState(IncidentState):
    status = WorkItemStatus.CLOSED

    def can_transition_to(self, target: WorkItemStatus) -> bool:
        return False


class StateMachine:
    """Validates lifecycle transitions and enforces RCA-before-closure."""

    def __init__(self) -> None:
        self._states: dict[WorkItemStatus, IncidentState] = {
            WorkItemStatus.OPEN: OpenState(),
            WorkItemStatus.INVESTIGATING: InvestigatingState(),
            WorkItemStatus.RESOLVED: ResolvedState(),
            WorkItemStatus.CLOSED: ClosedState(),
        }

    def validate(self, item: WorkItem, target: WorkItemStatus, rca: RCARecord | None) -> None:
        if item.status == target:
            return
        self._states[item.status].validate_transition(target, rca)
