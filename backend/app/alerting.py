from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import ComponentType, Severity, SignalIn


class AlertingStrategy(ABC):
    """Strategy interface for component-specific severity and responder routing."""

    @abstractmethod
    def severity_for(self, signal: SignalIn) -> Severity:
        raise NotImplementedError

    @abstractmethod
    def channel_for(self, signal: SignalIn) -> str:
        raise NotImplementedError


class DatabaseAlertingStrategy(AlertingStrategy):
    def severity_for(self, signal: SignalIn) -> Severity:
        return Severity.P0 if signal.component_type == ComponentType.RDBMS else Severity.P1

    def channel_for(self, signal: SignalIn) -> str:
        return "pagerduty:database-oncall"


class CacheAlertingStrategy(AlertingStrategy):
    def severity_for(self, signal: SignalIn) -> Severity:
        return Severity.P2

    def channel_for(self, signal: SignalIn) -> str:
        return "slack:cache-responder"


class QueueAlertingStrategy(AlertingStrategy):
    def severity_for(self, signal: SignalIn) -> Severity:
        return Severity.P2

    def channel_for(self, signal: SignalIn) -> str:
        return "slack:platform-async"


class ApiAlertingStrategy(AlertingStrategy):
    def severity_for(self, signal: SignalIn) -> Severity:
        if signal.latency_ms and signal.latency_ms > 2_000:
            return Severity.P1
        return Severity.P2

    def channel_for(self, signal: SignalIn) -> str:
        return "slack:api-oncall"


class McpHostAlertingStrategy(AlertingStrategy):
    def severity_for(self, signal: SignalIn) -> Severity:
        return Severity.P1

    def channel_for(self, signal: SignalIn) -> str:
        return "pagerduty:mcp-host-oncall"


class AlertingStrategyFactory:
    """Central place to swap alerting behavior without changing ingestion workers."""

    def __init__(self) -> None:
        self._strategies: dict[ComponentType, AlertingStrategy] = {
            ComponentType.RDBMS: DatabaseAlertingStrategy(),
            ComponentType.NOSQL: DatabaseAlertingStrategy(),
            ComponentType.CACHE: CacheAlertingStrategy(),
            ComponentType.QUEUE: QueueAlertingStrategy(),
            ComponentType.API: ApiAlertingStrategy(),
            ComponentType.MCP_HOST: McpHostAlertingStrategy(),
        }

    def for_signal(self, signal: SignalIn) -> AlertingStrategy:
        return self._strategies[signal.component_type]
