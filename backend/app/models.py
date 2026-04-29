from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Column, Integer, MetaData, String, Table


metadata = MetaData()

work_items_table = Table(
    "work_items",
    metadata,
    Column("id", String, primary_key=True),
    Column("component_id", String, nullable=False),
    Column("component_type", String, nullable=False),
    Column("service", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("status", String, nullable=False),
    Column("signal_count", Integer, nullable=False),
    Column("first_signal_at", String, nullable=False),
    Column("last_signal_at", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("mttr_seconds", Integer, nullable=True),
)

rcas_table = Table(
    "rcas",
    metadata,
    Column("work_item_id", String, primary_key=True),
    Column("incident_start", String, nullable=False),
    Column("incident_end", String, nullable=False),
    Column("root_cause_category", String, nullable=False),
    Column("fix_applied", String, nullable=False),
    Column("prevention_steps", String, nullable=False),
    Column("submitted_at", String, nullable=False),
    Column("mttr_seconds", Integer, nullable=False),
)

audit_events_table = Table(
    "audit_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_item_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("from_status", String, nullable=True),
    Column("to_status", String, nullable=True),
    Column("actor", String, nullable=False),
    Column("message", String, nullable=False),
    Column("created_at", String, nullable=False),
)


class ComponentType(str, Enum):
    API = "API"
    MCP_HOST = "MCP_HOST"
    CACHE = "CACHE"
    QUEUE = "QUEUE"
    RDBMS = "RDBMS"
    NOSQL = "NOSQL"


class Severity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class WorkItemStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SignalIn(BaseModel):
    component_id: str = Field(min_length=2, max_length=120)
    component_type: ComponentType
    service: str = Field(min_length=1, max_length=120)
    error_code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    latency_ms: int | None = Field(default=None, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class SignalRecord(SignalIn):
    id: str = Field(default_factory=lambda: str(uuid4()))
    work_item_id: str | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkItem(BaseModel):
    id: str
    component_id: str
    component_type: ComponentType
    service: str
    severity: Severity
    status: WorkItemStatus = WorkItemStatus.OPEN
    signal_count: int = 0
    first_signal_at: datetime
    last_signal_at: datetime
    created_at: datetime
    updated_at: datetime
    mttr_seconds: int | None = None


class RCAIn(BaseModel):
    incident_start: datetime
    incident_end: datetime
    root_cause_category: str = Field(min_length=3, max_length=120)
    fix_applied: str = Field(min_length=10, max_length=4_000)
    prevention_steps: str = Field(min_length=10, max_length=4_000)

    @model_validator(mode="after")
    def validate_window(self) -> "RCAIn":
        if self.incident_start.tzinfo is None:
            self.incident_start = self.incident_start.replace(tzinfo=timezone.utc)
        if self.incident_end.tzinfo is None:
            self.incident_end = self.incident_end.replace(tzinfo=timezone.utc)
        if self.incident_end < self.incident_start:
            raise ValueError("incident_end must be greater than or equal to incident_start")
        if self.incident_end > datetime.now(timezone.utc):
            raise ValueError("incident_end cannot be in the future")
        return self


class RCARecord(RCAIn):
    work_item_id: str
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mttr_seconds: int


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    work_item_id: str
    event_type: str = Field(min_length=2, max_length=80)
    from_status: WorkItemStatus | None = None
    to_status: WorkItemStatus | None = None
    actor: str = Field(default="system", min_length=2, max_length=120)
    message: str = Field(min_length=2, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusUpdate(BaseModel):
    status: WorkItemStatus
    actor: str = Field(default="responder", min_length=2, max_length=120)


class AcceptedResponse(BaseModel):
    accepted: int
    dropped: int = 0
    queue_depth: int
