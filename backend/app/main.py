from __future__ import annotations

import asyncio
import os
import resource
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.ingestion import FixedWindowRateLimiter, IngestionEngine
from app.models import AcceptedResponse, AuditEvent, RCAIn, SignalIn, StatusUpdate, WorkItemStatus
from app.storage import (
    BatchProcessor,
    DashboardCache,
    RawSignalStore,
    RedisDashboardCache,
    RedisTimeSeriesAggregator,
    TimeSeriesAggregator,
    WorkItemRepository,
)
from app.workflow import InvalidTransition, StateMachine

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
STARTED_AT = datetime.now(timezone.utc)
API_KEY = os.getenv("IMS_API_KEY", "dev-secret")
QUEUE_SIZE = 25_000
REDIS_URL = os.getenv("REDIS_URL")

signals_ingested_total = Counter("signals_ingested_total", "Total signals accepted into the IMS ingestion queue.")
signals_dropped_total = Counter("signals_dropped_total", "Total signals rejected or dropped by IMS.")
incident_resolution_time_seconds = Histogram(
    "incident_resolution_time_seconds",
    "Incident resolution time in seconds from RCA incident_start to incident_end.",
    buckets=(60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400, float("inf")),
)

repo = WorkItemRepository(DATA_DIR / "ims.sqlite3")
raw_store = RawSignalStore(DATA_DIR / "raw_signals.jsonl")
cache = RedisDashboardCache(REDIS_URL) if REDIS_URL else DashboardCache()
aggregations = RedisTimeSeriesAggregator(REDIS_URL) if REDIS_URL else TimeSeriesAggregator()
batch_processor = BatchProcessor(raw_store, repo, cache)
engine = IngestionEngine(repo, batch_processor, cache, aggregations, queue_size=QUEUE_SIZE)
rate_limiter = FixedWindowRateLimiter(limit=5_000, window_seconds=60)
state_machine = StateMachine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability_task = asyncio.create_task(print_throughput_metrics())
    await engine.start()
    try:
        yield
    finally:
        observability_task.cancel()
        await asyncio.gather(observability_task, return_exceptions=True)
        await engine.stop()


app = FastAPI(title="Mission-Critical IMS", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def print_throughput_metrics() -> None:
    previous_processed = 0
    while True:
        await asyncio.sleep(5)
        accepted, processed, dropped = await engine.metrics.snapshot()
        current_rate = (processed - previous_processed) / 5
        previous_processed = processed
        pending_batch = await batch_processor.pending_count()
        print(
            f"[IMS PULSE] TPS: {current_rate:.2f} | Queue: {engine.queue.qsize()}/{QUEUE_SIZE} | "
            f"Batched: {pending_batch} | Dropped: {dropped}"
        )


def client_id(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def has_valid_api_key(request: Request) -> bool:
    header_key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    bearer_key = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    return API_KEY in {header_key, bearer_key}


@app.middleware("http")
async def ingestion_security_and_rate_limit_middleware(request: Request, call_next):
    # Only ingestion mutates the high-volume path; dashboard/read APIs stay unauthenticated
    # for local assessment convenience.
    is_signal_route = request.method == "POST" and request.url.path in {"/signals", "/signals/bulk"}
    if is_signal_route and not has_valid_api_key(request):
        signals_dropped_total.inc()
        return JSONResponse(status_code=401, content={"detail": "missing or invalid API key"})
    if request.method == "POST" and request.url.path == "/signals":
        if not await rate_limiter.allow(client_id(request), cost=1):
            signals_dropped_total.inc()
            return JSONResponse(status_code=429, content={"detail": "single IP exceeded 5000 signals/minute"})
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, object]:
    accepted, processed, dropped = await engine.metrics.snapshot()
    uptime_seconds = int((datetime.now(timezone.utc) - STARTED_AT).total_seconds())
    sqlite_ok = await repo.ping()
    jsonl_ok = await raw_store.ping()
    return {
        "status": "ok",
        "queue_depth": engine.queue.qsize(),
        "queue_capacity": QUEUE_SIZE,
        "pending_batch": await batch_processor.pending_count(),
        "uptime_seconds": uptime_seconds,
        "memory_usage_bytes": memory_usage_bytes(),
        "storage": {"sqlite": "ok" if sqlite_ok else "down", "jsonl": "ok" if jsonl_ok else "down"},
        "accepted": accepted,
        "processed": processed,
        "dropped": dropped,
    }


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": "Mission-Critical Incident Management System",
        "status": "running",
        "dashboard": "http://localhost:5173",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


def memory_usage_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage
    return usage * 1024


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/signals", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def ingest_signal(signal: SignalIn, request: Request) -> AcceptedResponse:
    accepted = await engine.submit(signal)
    if not accepted:
        signals_dropped_total.inc()
        raise HTTPException(status_code=503, detail="ingestion buffer saturated; retry later")
    signals_ingested_total.inc()
    return AcceptedResponse(accepted=1, queue_depth=engine.queue.qsize())


@app.post("/signals/bulk", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def ingest_bulk(signals: list[SignalIn], request: Request) -> AcceptedResponse:
    if len(signals) > 5_000:
        raise HTTPException(status_code=413, detail="bulk payload limit is 5000 signals")
    if not await rate_limiter.allow(client_id(request), cost=max(1, len(signals))):
        signals_dropped_total.inc(len(signals))
        raise HTTPException(status_code=429, detail="single IP exceeded 5000 signals/minute")
    accepted = await engine.submit_many(signals)
    if not accepted:
        signals_dropped_total.inc(len(signals))
        raise HTTPException(status_code=503, detail="ingestion buffer saturated; retry later")
    signals_ingested_total.inc(len(signals))
    return AcceptedResponse(accepted=len(signals), dropped=0, queue_depth=engine.queue.qsize())


@app.get("/incidents")
async def list_incidents(include_closed: bool = False) -> list[dict]:
    items = await repo.list_work_items(include_closed=True) if include_closed else await cache.list_active()
    weight = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return [item.model_dump(mode="json") for item in sorted(items, key=lambda item: (weight[item.severity.value], item.created_at))]


@app.get("/incidents/{work_item_id}")
async def incident_detail(work_item_id: str) -> dict:
    item = await repo.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="incident not found")
    signals = await raw_store.by_work_item(work_item_id)
    rca = await repo.get_rca(work_item_id)
    audit_events = await repo.list_audit_events(work_item_id)
    return {
        "incident": item.model_dump(mode="json"),
        "signals": [signal.model_dump(mode="json") for signal in signals],
        "rca": rca.model_dump(mode="json") if rca else None,
        "audit_events": [event.model_dump(mode="json") for event in audit_events],
    }


@app.patch("/incidents/{work_item_id}/status")
async def update_status(work_item_id: str, update: StatusUpdate) -> dict:
    item = await repo.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="incident not found")
    rca = await repo.get_rca(work_item_id)
    try:
        state_machine.validate(item, update.status, rca)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if item.status == update.status:
        return item.model_dump(mode="json")
    if update.status == WorkItemStatus.CLOSED:
        assert rca is not None
        updated = await repo.close_work_item(work_item_id, rca)
    else:
        updated = await repo.update_status(work_item_id, update.status)
    await repo.append_audit_event(
        AuditEvent(
            work_item_id=work_item_id,
            event_type="status_transition",
            from_status=item.status,
            to_status=updated.status,
            actor=update.actor,
            message=f"{update.actor} moved incident from {item.status.value} to {updated.status.value}",
        )
    )
    if updated.status == WorkItemStatus.CLOSED:
        await cache.remove(work_item_id)
    else:
        await cache.put(updated)
    return updated.model_dump(mode="json")


@app.post("/incidents/{work_item_id}/rca")
async def submit_rca(work_item_id: str, rca: RCAIn) -> dict:
    item = await repo.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="incident not found")
    record = await repo.upsert_rca(work_item_id, rca)
    await repo.append_audit_event(
        AuditEvent(
            work_item_id=work_item_id,
            event_type="rca_submitted",
            actor="responder",
            message=f"RCA submitted with MTTR {record.mttr_seconds} seconds",
        )
    )
    incident_resolution_time_seconds.observe(record.mttr_seconds)
    refreshed = await repo.get_work_item(work_item_id)
    if refreshed:
        await cache.put(refreshed)
    return record.model_dump(mode="json")


@app.get("/aggregations")
async def get_aggregations() -> dict[str, int]:
    return await aggregations.snapshot()
