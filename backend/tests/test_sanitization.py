from app.ingestion import REDACTED, sanitize_signal
from app.models import ComponentType, SignalIn


def test_sanitize_signal_redacts_internal_ips_and_tokens() -> None:
    signal = SignalIn(
        component_id="RDBMS_PRIMARY_01",
        component_type=ComponentType.RDBMS,
        service="orders-platform",
        error_code="CONNECTION_TIMEOUT",
        message="failure from 10.1.2.3 with bearer abc.def",
        payload={
            "authorization": "Bearer secret-token",
            "url": "https://svc.local/callback?token=supersecret",
            "nested": {"internal_ip": "192.168.10.44"},
        },
    )

    sanitized = sanitize_signal(signal)

    assert REDACTED in sanitized.message
    assert sanitized.payload["authorization"] == REDACTED
    assert "token=[REDACTED]" in sanitized.payload["url"]
    assert sanitized.payload["nested"]["internal_ip"] == REDACTED
