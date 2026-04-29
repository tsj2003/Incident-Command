from __future__ import annotations

import asyncio
import functools
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import redis.asyncio as redis

from app.models import AuditEvent, RCAIn, RCARecord, SignalRecord, WorkItem, WorkItemStatus

T = TypeVar("T")


def retry_on_failure(attempts: int = 5, base_delay: float = 0.1):
    """Retry async SQLite writes that can fail during short lock windows."""

    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    return await func(*args, **kwargs)
                except (sqlite3.OperationalError, OSError) as exc:
                    last_error = exc
                    await asyncio.sleep(base_delay * (2**attempt))
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator


async def _to_thread(fn: Callable[[], T]) -> T:
    return await asyncio.to_thread(fn)


def _dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class RawSignalStore:
    """Append-only document store for raw signals, backed by JSONL plus a hot index."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._by_work_item: dict[str, list[SignalRecord]] = defaultdict(list)

    async def append(self, signal: SignalRecord) -> None:
        await self.append_many([signal])

    async def append_many(self, signals: list[SignalRecord]) -> None:
        if not signals:
            return
        payloads = [signal.model_dump(mode="json") for signal in signals]
        async with self._lock:
            for signal in signals:
                self._by_work_item[signal.work_item_id or ""].append(signal)
            await asyncio.to_thread(self._append_lines, payloads)

    def _append_lines(self, payloads: list[dict[str, Any]]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(json.dumps(payload, separators=(",", ":")) + "\n")

    async def by_work_item(self, work_item_id: str) -> list[SignalRecord]:
        return list(self._by_work_item.get(work_item_id, []))

    async def ping(self) -> bool:
        def op() -> bool:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8"):
                    return True
            except OSError:
                return False

        return await asyncio.to_thread(op)


class WorkItemRepository:
    """Transactional SQLite source of truth for incidents and RCA records."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY,
                    component_id TEXT NOT NULL,
                    component_type TEXT NOT NULL,
                    service TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    signal_count INTEGER NOT NULL,
                    first_signal_at TEXT NOT NULL,
                    last_signal_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    mttr_seconds INTEGER
                );
                CREATE TABLE IF NOT EXISTS rcas (
                    work_item_id TEXT PRIMARY KEY REFERENCES work_items(id),
                    incident_start TEXT NOT NULL,
                    incident_end TEXT NOT NULL,
                    root_cause_category TEXT NOT NULL,
                    fix_applied TEXT NOT NULL,
                    prevention_steps TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    mttr_seconds INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    actor TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @retry_on_failure()
    async def create_work_item(self, item: WorkItem) -> WorkItem:
        def op() -> WorkItem:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO work_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.component_id,
                        item.component_type.value,
                        item.service,
                        item.severity.value,
                        item.status.value,
                        item.signal_count,
                        _dt(item.first_signal_at),
                        _dt(item.last_signal_at),
                        _dt(item.created_at),
                        _dt(item.updated_at),
                        item.mttr_seconds,
                    ),
                )
            return item

        async with self._lock:
            return await _to_thread(op)

    @retry_on_failure()
    async def increment_signal_counts(self, signals: list[SignalRecord]) -> list[WorkItem]:
        if not signals:
            return []

        counts: dict[str, int] = defaultdict(int)
        latest_ts: dict[str, datetime] = {}
        for signal in signals:
            if signal.work_item_id is None:
                continue
            counts[signal.work_item_id] += 1
            current = latest_ts.get(signal.work_item_id)
            if current is None or signal.timestamp > current:
                latest_ts[signal.work_item_id] = signal.timestamp

        def op() -> list[WorkItem]:
            now = datetime.now(timezone.utc)
            updated: list[WorkItem] = []
            with self._connect() as conn:
                conn.execute("BEGIN")
                for work_item_id, count in counts.items():
                    conn.execute(
                        """
                        UPDATE work_items
                        SET signal_count = signal_count + ?,
                            last_signal_at = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (count, _dt(latest_ts[work_item_id]), _dt(now), work_item_id),
                    )
                for work_item_id in counts:
                    row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
                    if row is not None:
                        updated.append(self._row_to_work_item(row))
                conn.commit()
            return updated

        async with self._lock:
            return await _to_thread(op)

    async def list_work_items(self, include_closed: bool = False) -> list[WorkItem]:
        def op() -> list[WorkItem]:
            with self._connect() as conn:
                if include_closed:
                    rows = conn.execute("SELECT * FROM work_items").fetchall()
                else:
                    rows = conn.execute("SELECT * FROM work_items WHERE status != 'CLOSED'").fetchall()
            return [self._row_to_work_item(row) for row in rows]

        return await _to_thread(op)

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        def op() -> WorkItem | None:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
            return self._row_to_work_item(row) if row else None

        return await _to_thread(op)

    @retry_on_failure()
    async def update_status(self, work_item_id: str, status: WorkItemStatus) -> WorkItem:
        def op() -> WorkItem:
            now = datetime.now(timezone.utc)
            with self._connect() as conn:
                conn.execute(
                    "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, _dt(now), work_item_id),
                )
                row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
                if row is None:
                    raise KeyError(work_item_id)
                return self._row_to_work_item(row)

        async with self._lock:
            return await _to_thread(op)

    @retry_on_failure()
    async def close_work_item(self, work_item_id: str, rca: RCARecord) -> WorkItem:
        def op() -> WorkItem:
            now = datetime.now(timezone.utc)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE work_items
                    SET status = ?,
                        mttr_seconds = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (WorkItemStatus.CLOSED.value, rca.mttr_seconds, _dt(now), work_item_id),
                )
                row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
                if row is None:
                    raise KeyError(work_item_id)
                return self._row_to_work_item(row)

        async with self._lock:
            return await _to_thread(op)

    @retry_on_failure()
    async def upsert_rca(self, work_item_id: str, rca: RCAIn) -> RCARecord:
        mttr_seconds = int((rca.incident_end - rca.incident_start).total_seconds())
        record = RCARecord(work_item_id=work_item_id, mttr_seconds=mttr_seconds, **rca.model_dump())

        def op() -> RCARecord:
            with self._connect() as conn:
                conn.execute("BEGIN")
                conn.execute(
                    """
                    INSERT INTO rcas VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        incident_start = excluded.incident_start,
                        incident_end = excluded.incident_end,
                        root_cause_category = excluded.root_cause_category,
                        fix_applied = excluded.fix_applied,
                        prevention_steps = excluded.prevention_steps,
                        submitted_at = excluded.submitted_at,
                        mttr_seconds = excluded.mttr_seconds
                    """,
                    (
                        record.work_item_id,
                        _dt(record.incident_start),
                        _dt(record.incident_end),
                        record.root_cause_category,
                        record.fix_applied,
                        record.prevention_steps,
                        _dt(record.submitted_at),
                        record.mttr_seconds,
                    ),
                )
                conn.execute(
                    "UPDATE work_items SET mttr_seconds = ?, updated_at = ? WHERE id = ?",
                    (record.mttr_seconds, _dt(record.submitted_at), work_item_id),
                )
                conn.commit()
            return record

        async with self._lock:
            return await _to_thread(op)

    async def get_rca(self, work_item_id: str) -> RCARecord | None:
        def op() -> RCARecord | None:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM rcas WHERE work_item_id = ?", (work_item_id,)).fetchone()
            return self._row_to_rca(row) if row else None

        return await _to_thread(op)

    @retry_on_failure()
    async def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        def op() -> AuditEvent:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.work_item_id,
                        event.event_type,
                        event.from_status.value if event.from_status else None,
                        event.to_status.value if event.to_status else None,
                        event.actor,
                        event.message,
                        _dt(event.created_at),
                    ),
                )
            return event

        async with self._lock:
            return await _to_thread(op)

    async def list_audit_events(self, work_item_id: str) -> list[AuditEvent]:
        def op() -> list[AuditEvent]:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE work_item_id = ? ORDER BY created_at ASC",
                    (work_item_id,),
                ).fetchall()
            return [self._row_to_audit_event(row) for row in rows]

        return await _to_thread(op)

    async def ping(self) -> bool:
        def op() -> bool:
            try:
                with self._connect() as conn:
                    conn.execute("SELECT 1").fetchone()
                return True
            except sqlite3.Error:
                return False

        return await _to_thread(op)

    def _row_to_work_item(self, row: sqlite3.Row) -> WorkItem:
        return WorkItem(
            id=row["id"],
            component_id=row["component_id"],
            component_type=row["component_type"],
            service=row["service"],
            severity=row["severity"],
            status=row["status"],
            signal_count=row["signal_count"],
            first_signal_at=_parse_dt(row["first_signal_at"]),
            last_signal_at=_parse_dt(row["last_signal_at"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            mttr_seconds=row["mttr_seconds"],
        )

    def _row_to_rca(self, row: sqlite3.Row) -> RCARecord:
        return RCARecord(
            work_item_id=row["work_item_id"],
            incident_start=_parse_dt(row["incident_start"]),
            incident_end=_parse_dt(row["incident_end"]),
            root_cause_category=row["root_cause_category"],
            fix_applied=row["fix_applied"],
            prevention_steps=row["prevention_steps"],
            submitted_at=_parse_dt(row["submitted_at"]),
            mttr_seconds=row["mttr_seconds"],
        )

    def _row_to_audit_event(self, row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            work_item_id=row["work_item_id"],
            event_type=row["event_type"],
            from_status=row["from_status"],
            to_status=row["to_status"],
            actor=row["actor"],
            message=row["message"],
            created_at=_parse_dt(row["created_at"]),
        )


class DashboardCache:
    """Hot-path in-memory view used by the dashboard instead of polling SQLite."""

    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}
        self._lock = asyncio.Lock()

    async def put(self, item: WorkItem) -> None:
        async with self._lock:
            self._items[item.id] = item

    async def remove(self, work_item_id: str) -> None:
        async with self._lock:
            self._items.pop(work_item_id, None)

    async def list_active(self) -> list[WorkItem]:
        weight = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        async with self._lock:
            active = [item for item in self._items.values() if item.status.value != "CLOSED"]
        return sorted(active, key=lambda item: (weight[item.severity.value], item.created_at))


class RedisDashboardCache:
    """Production hot-path cache backed by Redis instead of process memory."""

    def __init__(self, url: str, prefix: str = "ims:incident") -> None:
        self.redis = redis.from_url(url, decode_responses=True)
        self.prefix = prefix

    def _key(self, work_item_id: str) -> str:
        return f"{self.prefix}:{work_item_id}"

    async def put(self, item: WorkItem) -> None:
        await self.redis.set(self._key(item.id), item.model_dump_json())

    async def remove(self, work_item_id: str) -> None:
        await self.redis.delete(self._key(work_item_id))

    async def list_active(self) -> list[WorkItem]:
        keys = [key async for key in self.redis.scan_iter(f"{self.prefix}:*")]
        if not keys:
            return []
        raw_items = await self.redis.mget(keys)
        items = [WorkItem.model_validate_json(raw) for raw in raw_items if raw]
        weight = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        active = [item for item in items if item.status != WorkItemStatus.CLOSED]
        return sorted(active, key=lambda item: (weight[item.severity.value], item.created_at))


class TimeSeriesAggregator:
    """Minute-bucket counters for lightweight operational aggregation."""

    def __init__(self) -> None:
        self._buckets: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def record(self, component_type: str, at: datetime) -> None:
        bucket = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        async with self._lock:
            self._buckets[f"{bucket}:{component_type}"] += 1

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return dict(self._buckets)


class RedisTimeSeriesAggregator:
    """Production aggregation sink using Redis counters."""

    def __init__(self, url: str, prefix: str = "ims:agg") -> None:
        self.redis = redis.from_url(url, decode_responses=True)
        self.prefix = prefix

    async def record(self, component_type: str, at: datetime) -> None:
        bucket = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        await self.redis.incr(f"{self.prefix}:{bucket}:{component_type}")

    async def snapshot(self) -> dict[str, int]:
        keys = [key async for key in self.redis.scan_iter(f"{self.prefix}:*")]
        if not keys:
            return {}
        values = await self.redis.mget(keys)
        return {key.removeprefix(f"{self.prefix}:"): int(value or 0) for key, value in zip(keys, values)}


class BatchProcessor:
    """Flush raw signals and source-of-truth count updates in high-throughput batches."""

    def __init__(
        self,
        raw_store: RawSignalStore,
        repo: WorkItemRepository,
        cache: DashboardCache,
        flush_interval_seconds: float = 1.0,
        max_batch_size: int = 1_000,
    ) -> None:
        self.raw_store = raw_store
        self.repo = repo
        self.cache = cache
        self.flush_interval_seconds = flush_interval_seconds
        self.max_batch_size = max_batch_size
        self._buffer: list[SignalRecord] = []
        self._lock = asyncio.Lock()
        self._flush_requested = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        await self.flush()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def enqueue(self, signal: SignalRecord) -> None:
        # Worker tasks only append to memory. Disk and SQLite writes happen in flush().
        async with self._lock:
            self._buffer.append(signal)
            if len(self._buffer) >= self.max_batch_size:
                self._flush_requested.set()

    async def flush(self) -> int:
        async with self._lock:
            if not self._buffer:
                return 0
            batch = self._buffer
            self._buffer = []
            self._flush_requested.clear()

        await self.raw_store.append_many(batch)
        # Grouping count deltas by work_item_id keeps SQLite writes proportional to
        # active incidents, not raw signal volume.
        updated_items = await self.repo.increment_signal_counts(batch)
        for item in updated_items:
            await self.cache.put(item)
        return len(batch)

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._buffer)

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._flush_requested.wait(), timeout=self.flush_interval_seconds)
            except asyncio.TimeoutError:
                pass
            await self.flush()
