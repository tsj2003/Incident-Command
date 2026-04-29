from fastapi.testclient import TestClient

from app.main import app


def test_signal_ingestion_requires_api_key() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/signals",
            json={
                "component_id": "RDBMS_PRIMARY_01",
                "component_type": "RDBMS",
                "service": "orders-platform",
                "error_code": "CONNECTION_TIMEOUT",
                "message": "connection pool exhausted",
            },
        )

    assert response.status_code == 401


def test_health_exposes_storage_memory_and_queue_fields() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["queue_capacity"] == 25_000
    assert body["memory_usage_bytes"] > 0
    assert body["storage"]["sqlite"] == "ok"
    assert body["storage"]["jsonl"] == "ok"


def test_metrics_endpoint_is_prometheus_text() -> None:
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "signals_ingested_total" in response.text
