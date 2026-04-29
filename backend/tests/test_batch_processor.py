import asyncio
from datetime import datetime, timezone

from app.models import ComponentType, Severity, SignalRecord, WorkItem, WorkItemStatus
from app.models import AuditEvent
from app.storage import BatchProcessor, DashboardCache, RawSignalStore, WorkItemRepository
from app.ingestion import IngestionEngine


def test_batch_processor_flushes_raw_signals_and_count_deltas(tmp_path) -> None:
    asyncio.run(_exercise_batch_processor(tmp_path))


async def _exercise_batch_processor(tmp_path) -> None:
    repo = WorkItemRepository(tmp_path / "ims.sqlite3")
    raw_store = RawSignalStore(tmp_path / "raw.jsonl")
    cache = DashboardCache()
    batcher = BatchProcessor(raw_store, repo, cache, max_batch_size=1_000)
    now = datetime.now(timezone.utc)
    item = WorkItem(
        id="wi-batch-1",
        component_id="CACHE_CLUSTER_01",
        component_type=ComponentType.CACHE,
        service="session-cache",
        severity=Severity.P2,
        status=WorkItemStatus.OPEN,
        signal_count=0,
        first_signal_at=now,
        last_signal_at=now,
        created_at=now,
        updated_at=now,
    )
    await repo.create_work_item(item)

    for idx in range(5):
        await batcher.enqueue(
            SignalRecord(
                component_id="CACHE_CLUSTER_01",
                component_type=ComponentType.CACHE,
                service="session-cache",
                error_code="TIMEOUT",
                message=f"cache timeout {idx}",
                timestamp=now,
                work_item_id=item.id,
            )
        )

    flushed = await batcher.flush()
    updated = await repo.get_work_item(item.id)
    linked = await raw_store.by_work_item(item.id)

    assert flushed == 5
    assert updated is not None
    assert updated.signal_count == 5
    assert len(linked) == 5


def test_bulk_submit_rejects_when_queue_lacks_capacity(tmp_path) -> None:
    asyncio.run(_exercise_queue_backpressure(tmp_path))


async def _exercise_queue_backpressure(tmp_path) -> None:
    repo = WorkItemRepository(tmp_path / "ims.sqlite3")
    raw_store = RawSignalStore(tmp_path / "raw.jsonl")
    cache = DashboardCache()
    batcher = BatchProcessor(raw_store, repo, cache)
    engine = IngestionEngine(repo, batcher, cache, aggregations=_NoopAggregations(), queue_size=1, workers=0)
    now = datetime.now(timezone.utc)
    signals = [
        SignalRecord(
            component_id="CACHE_CLUSTER_01",
            component_type=ComponentType.CACHE,
            service="session-cache",
            error_code="TIMEOUT",
            message=f"cache timeout {idx}",
            timestamp=now,
        )
        for idx in range(2)
    ]

    accepted = await engine.submit_many(signals)

    assert accepted is False
    assert engine.queue.qsize() == 0


class _NoopAggregations:
    async def record(self, component_type: str, at: datetime) -> None:
        return None


def test_audit_events_are_persisted(tmp_path) -> None:
    asyncio.run(_exercise_audit_events(tmp_path))


async def _exercise_audit_events(tmp_path) -> None:
    repo = WorkItemRepository(tmp_path / "ims.sqlite3")
    event = AuditEvent(
        work_item_id="wi-audit-1",
        event_type="status_transition",
        from_status=WorkItemStatus.OPEN,
        to_status=WorkItemStatus.INVESTIGATING,
        actor="alice",
        message="alice acknowledged incident",
    )

    await repo.append_audit_event(event)
    events = await repo.list_audit_events("wi-audit-1")

    assert len(events) == 1
    assert events[0].actor == "alice"
    assert events[0].to_status == WorkItemStatus.INVESTIGATING
