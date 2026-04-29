from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.alerting import AlertingStrategyFactory
from app.models import SignalIn, SignalRecord, WorkItem, WorkItemStatus
from app.storage import BatchProcessor, DashboardCache, TimeSeriesAggregator, WorkItemRepository

INTERNAL_IP_RE = re.compile(r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b192\.168\.\d{1,3}\.\d{1,3}\b|\b172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}\b")
TOKEN_VALUE_RE = re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+|([?&](?:token|api_key|apikey|access_token)=)[^&\s]+")
SENSITIVE_KEYS = {"authorization", "auth", "token", "api_key", "apikey", "access_token", "refresh_token", "password", "secret"}
REDACTED = "[REDACTED]"


@dataclass
class DebounceBucket:
    """Tracks the active incident bucket for one component within the debounce window."""

    work_item_id: str
    started_at: datetime


class Debouncer:
    """Maps noisy component bursts to one work item while preserving every raw signal."""

    def __init__(self, window_seconds: int = 10) -> None:
        self.window = timedelta(seconds=window_seconds)
        self._buckets: dict[str, DebounceBucket] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def resolve(self, signal: SignalIn, create_item) -> str:
        async with self._locks[signal.component_id]:
            now = signal.timestamp
            bucket = self._buckets.get(signal.component_id)
            if bucket and now - bucket.started_at <= self.window:
                return bucket.work_item_id
            work_item_id = await create_item()
            self._buckets[signal.component_id] = DebounceBucket(work_item_id=work_item_id, started_at=now)
            return work_item_id


def sanitize_signal(signal: SignalIn) -> SignalIn:
    """Scrub sensitive values before the signal is persisted into the JSONL lake."""

    data = signal.model_dump()
    data["message"] = _sanitize_value(data["message"])
    data["payload"] = _sanitize_value(data["payload"])
    return SignalIn(**data)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            if key.lower() in SENSITIVE_KEYS:
                cleaned[key] = REDACTED
            else:
                cleaned[key] = _sanitize_value(nested)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        value = INTERNAL_IP_RE.sub(REDACTED, value)
        value = TOKEN_VALUE_RE.sub(lambda match: f"{match.group(1) or match.group(2)}{REDACTED}", value)
        return value
    return value


class FixedWindowRateLimiter:
    """Small in-process fixed-window limiter for API abuse protection."""

    def __init__(self, limit: int = 5_000, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clients: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, client_id: str, cost: int = 1) -> bool:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            used, window_started = self._clients.get(client_id, (0, now))
            if now - window_started >= self.window_seconds:
                used = 0
                window_started = now
            if used + cost > self.limit:
                self._clients[client_id] = (used, window_started)
                return False
            self._clients[client_id] = (used + cost, window_started)
            return True


class Metrics:
    """Thread-safe-ish async counters used by health and throughput logging."""

    def __init__(self) -> None:
        self.accepted = 0
        self.processed = 0
        self.dropped = 0
        self._lock = asyncio.Lock()

    async def incr(self, field: str, amount: int = 1) -> None:
        async with self._lock:
            setattr(self, field, getattr(self, field) + amount)

    async def snapshot(self) -> tuple[int, int, int]:
        async with self._lock:
            return self.accepted, self.processed, self.dropped


class IngestionEngine:
    """Owns the bounded queue, worker pool, debouncer, and batch handoff."""

    def __init__(
        self,
        repo: WorkItemRepository,
        batch_processor: BatchProcessor,
        cache: DashboardCache,
        aggregations: TimeSeriesAggregator,
        queue_size: int = 25_000,
        workers: int = 4,
    ) -> None:
        self.repo = repo
        self.batch_processor = batch_processor
        self.cache = cache
        self.aggregations = aggregations
        self.queue: asyncio.Queue[SignalIn] = asyncio.Queue(maxsize=queue_size)
        self.debouncer = Debouncer()
        self.alerting = AlertingStrategyFactory()
        self.metrics = Metrics()
        self.workers = workers
        self._tasks: list[asyncio.Task] = []
        self._submit_lock = asyncio.Lock()

    async def start(self) -> None:
        await self.batch_processor.start()
        self._tasks = [asyncio.create_task(self._worker(idx)) for idx in range(self.workers)]

    async def stop(self) -> None:
        try:
            await asyncio.wait_for(self.queue.join(), timeout=10)
        except asyncio.TimeoutError:
            await self.metrics.incr("dropped", self.queue.qsize())
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.batch_processor.stop()

    async def submit(self, signal: SignalIn) -> bool:
        async with self._submit_lock:
            try:
                self.queue.put_nowait(signal)
                await self.metrics.incr("accepted")
                return True
            except asyncio.QueueFull:
                await self.metrics.incr("dropped")
                return False

    async def submit_many(self, signals: list[SignalIn]) -> bool:
        """Atomically admit a bulk request or reject it before partial enqueue."""

        async with self._submit_lock:
            available = self.queue.maxsize - self.queue.qsize()
            if len(signals) > available:
                await self.metrics.incr("dropped", len(signals))
                return False
            for signal in signals:
                self.queue.put_nowait(signal)
            await self.metrics.incr("accepted", len(signals))
            return True

    async def _worker(self, idx: int) -> None:
        while True:
            signal = await self.queue.get()
            try:
                await self._process(signal)
                await self.metrics.incr("processed")
            finally:
                self.queue.task_done()

    async def _process(self, signal: SignalIn) -> None:
        async def create_item() -> str:
            now = datetime.now(timezone.utc)
            strategy = self.alerting.for_signal(signal)
            item = WorkItem(
                id=str(uuid4()),
                component_id=signal.component_id,
                component_type=signal.component_type,
                service=signal.service,
                severity=strategy.severity_for(signal),
                status=WorkItemStatus.OPEN,
                signal_count=0,
                first_signal_at=signal.timestamp,
                last_signal_at=signal.timestamp,
                created_at=now,
                updated_at=now,
            )
            await self.repo.create_work_item(item)
            await self.cache.put(item)
            print(f"ALERT {item.severity.value} {item.component_id} -> {strategy.channel_for(signal)}")
            return item.id

        work_item_id = await self.debouncer.resolve(signal, create_item)
        sanitized = sanitize_signal(signal)
        record = SignalRecord(**sanitized.model_dump(), work_item_id=work_item_id)
        await self.batch_processor.enqueue(record)
        await self.aggregations.record(signal.component_type.value, signal.timestamp)
