from app.alerting import AlertingStrategyFactory
from app.models import ComponentType, Severity, SignalIn


def test_mcp_host_failures_route_as_p1() -> None:
    signal = SignalIn(
        component_id="MCP_HOST_EAST_02",
        component_type=ComponentType.MCP_HOST,
        service="agent-runtime",
        error_code="HOST_UNREACHABLE",
        message="MCP host heartbeat failed",
        latency_ms=1200,
    )

    strategy = AlertingStrategyFactory().for_signal(signal)

    assert strategy.severity_for(signal) == Severity.P1
    assert strategy.channel_for(signal) == "pagerduty:mcp-host-oncall"
