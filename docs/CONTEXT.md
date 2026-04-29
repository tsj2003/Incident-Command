# IMS Implementation Context

This file is a handoff brief for any AI agent or developer who needs to understand, run, modify, or reimplement this Incident Management System without needing the original chat context.

## Assignment Goal

Build a Mission-Critical Incident Management System that can:

- Ingest high-volume failure signals from distributed stack components.
- Handle bursts without crashing when persistence is slow.
- Debounce duplicate component failures into a single incident work item.
- Store raw signals separately from structured incident records.
- Provide a workflow UI for responders.
- Require a complete Root Cause Analysis before an incident can be closed.
- Calculate MTTR automatically.
- Include tests, sample data, Docker Compose, documentation, and setup instructions.

## Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── alerting.py
│   │   ├── ingestion.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── storage.py
│   │   └── workflow.py
│   ├── scripts/
│   │   └── simulate_failure.py
│   ├── tests/
│   │   ├── test_alerting.py
│   │   └── test_rca_validation.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── Dockerfile
│   ├── index.html
│   └── package.json
├── docs/
│   ├── CONTEXT.md
│   ├── PLAN.md
│   └── PROMPTS.md
├── sample-data/
│   └── failure-events.json
├── docker-compose.yml
├── README.md
└── .gitignore
```

## Tech Stack Used

### Backend

- Python 3.14
- FastAPI for HTTP APIs
- asyncio for concurrency and async worker processing
- Pydantic v2 for request/response validation
- SQLite for the transactional source of truth
- JSONL file storage for raw signal audit logs
- pytest for backend tests
- Uvicorn for serving the API

### Frontend

- React 19
- Vite
- JavaScript JSX
- CSS
- lucide-react for icons

### DevOps / Runtime

- Docker Compose
- Backend container using Python slim image
- Frontend container using Node slim image
- Named Docker volume for backend runtime data

## Architecture Approach

The system separates data by purpose instead of putting every workload into one store.

### 1. Ingestion Path

Signals are accepted through:

- `POST /signals`
- `POST /signals/bulk`

The API validates each signal with Pydantic, applies rate limiting, and pushes accepted signals into a bounded async queue.

Signal writes require an API key. Send either `x-api-key: dev-secret` or `Authorization: Bearer dev-secret` locally. Override the key with `IMS_API_KEY`.

Important files:

- `backend/app/main.py`
- `backend/app/ingestion.py`
- `backend/app/models.py`

### 2. Backpressure

Backpressure is implemented with a bounded `asyncio.Queue`.

If the queue has capacity, signals are accepted.
If the queue remains full beyond a short timeout, the API returns `503` instead of allowing memory growth until the process crashes.

Rate limiting is implemented with a fixed-window limiter in `FixedWindowRateLimiter`.

Current limit:

```text
5,000 signals per IP per minute
```

Relevant file:

- `backend/app/ingestion.py`

### 3. Async Processing

Worker tasks continuously drain the queue and process signals.

Each signal processing step:

1. Resolves the debounced work item.
2. Creates a work item if needed.
3. Enqueues the raw signal into the `BatchProcessor`.
4. Updates timeseries aggregation counters.
5. The `BatchProcessor` flushes raw records and grouped SQLite count updates every 1 second or at 1,000 buffered signals.

Relevant file:

- `backend/app/ingestion.py`

### 4. Debouncing

Requirement:

If 100 signals arrive for the same `component_id` within 10 seconds, create only one work item and link all 100 signals to it.

Implementation:

- `Debouncer` tracks active component buckets for a 10 second window.
- It uses per-component async locks to prevent race-created duplicate work items.
- Every signal still gets stored as a raw signal with the same `work_item_id`.

Relevant file:

- `backend/app/ingestion.py`

### 5. Storage Split

The assignment asks for separate sinks. This implementation uses laptop-friendly equivalents.

#### Raw Signal Data Lake

Implemented as JSONL:

- `backend/data/raw_signals.jsonl`

This is append-only and acts as an audit log.

Class:

- `RawSignalStore`

Raw signal writes are flushed through `BatchProcessor`; do not put per-signal JSONL writes back into the ingestion worker hot path.

#### Source of Truth

Implemented as SQLite:

- `backend/data/ims.sqlite3`

Tables:

- `work_items`
- `rcas`

Class:

- `WorkItemRepository`

SQLite write operations use the `retry_on_failure` decorator with exponential backoff to tolerate short database lock windows.

#### Hot Dashboard Cache

Implemented as an in-memory dictionary sorted by severity for quick UI reads.

Class:

- `DashboardCache`

#### Aggregations

Implemented as in-memory minute buckets keyed by component type.

Endpoint:

- `GET /aggregations`

Class:

- `TimeSeriesAggregator`

Relevant file for all storage classes:

- `backend/app/storage.py`

Important high-throughput class:

- `BatchProcessor`

## Design Patterns Used

### Strategy Pattern: Alerting

Different component failures map to different severities and alert channels.

Examples:

- RDBMS failure -> P0 -> database on-call
- MCP host failure -> P1 -> MCP host on-call
- Cache failure -> P2 -> cache responder
- Queue failure -> P2 -> async platform channel

Relevant file:

- `backend/app/alerting.py`

Important classes:

- `AlertingStrategy`
- `DatabaseAlertingStrategy`
- `CacheAlertingStrategy`
- `QueueAlertingStrategy`
- `ApiAlertingStrategy`
- `McpHostAlertingStrategy`
- `AlertingStrategyFactory`

### State Pattern: Incident Workflow

Incident lifecycle:

```text
OPEN -> INVESTIGATING -> RESOLVED -> CLOSED
```

Closure requires a complete RCA.

Relevant file:

- `backend/app/workflow.py`

Important classes:

- `IncidentState`
- `OpenState`
- `InvestigatingState`
- `ResolvedState`
- `ClosedState`
- `StateMachine`

## RCA and MTTR

RCA is submitted through:

```text
POST /incidents/{work_item_id}/rca
```

Required RCA fields:

- `incident_start`
- `incident_end`
- `root_cause_category`
- `fix_applied`
- `prevention_steps`

Validation rules:

- Text fields cannot be empty or too short.
- `incident_end` must be greater than or equal to `incident_start`.
- `incident_end` cannot be in the future.
- An incident cannot transition to `CLOSED` without an RCA record.

MTTR is calculated as:

```text
incident_end - incident_start
```

The closure path persists `mttr_seconds` to the `work_items` table when moving to `CLOSED`.

Relevant files:

- `backend/app/models.py`
- `backend/app/storage.py`
- `backend/app/workflow.py`

## Backend API Endpoints

```text
GET    /health
POST   /signals
POST   /signals/bulk
GET    /incidents
GET    /incidents/{work_item_id}
PATCH  /incidents/{work_item_id}/status
POST   /incidents/{work_item_id}/rca
GET    /aggregations
```

## Frontend Approach

The frontend is a simple responder dashboard.

It provides:

- Active incident feed sorted by severity.
- Incident detail view.
- Raw signals linked to the selected incident.
- Status transition buttons.
- RCA submission form with date-time inputs, category dropdown, and text areas.
- Health/queue indicator.
- Polling every 3 seconds for live-ish updates.

Relevant files:

- `frontend/src/main.jsx`
- `frontend/src/styles.css`

## How To Run

### Docker Compose

```bash
docker compose up --build
```

Backend:

```text
http://localhost:8000
```

Frontend:

```text
http://localhost:5173
```

### Local Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Local Frontend

```bash
cd frontend
npm install
npm run dev
```

## How To Simulate Data

Start the backend first, then run:

```bash
cd backend
python scripts/simulate_failure.py --rate 10000 --duration 5 --api-key dev-secret
```

Expected result:

- Many RDBMS signals debounce into one P0 incident.
- Many MCP host signals debounce into one P1 incident.
- All raw signals remain linked to their work item.

## How To Test

```bash
cd backend
pytest
```

Current tests cover:

- Alerting strategy for MCP host failures.
- RCA field validation.
- RCA incident time-window validation.
- Future RCA end-time rejection.
- Rejection of `CLOSED` transition without RCA.
- Batch processor flushing raw signals and SQLite signal-count deltas.
- API-key rejection for unauthenticated signal ingestion.
- Signal sanitization for internal IPs and tokens before JSONL persistence.
- Health endpoint storage/memory fields and Prometheus `/metrics`.

## Known Simplifications

This is an assessment-friendly implementation, not a full production deployment.

The following production services are represented by local equivalents:

- NoSQL raw store -> JSONL file plus in-memory index.
- RDBMS source of truth -> SQLite.
- Cache -> in-memory dictionary.
- Timeseries DB -> in-memory minute buckets.
- Alerting integrations -> console output.

If moving to production, replace these with:

- Kafka, NATS, or Pulsar for ingestion buffering.
- S3, ClickHouse, OpenSearch, or BigQuery for raw signal/audit search.
- PostgreSQL for work items and RCA records.
- Redis for dashboard hot state.
- Prometheus, VictoriaMetrics, or TimescaleDB for aggregations.
- PagerDuty/Opsgenie/Slack integrations for alert delivery.

## Things A Future Agent Should Preserve

Do not remove these assignment-critical behaviors:

- Async ingestion and processing.
- Bounded queue backpressure.
- Rate limiting.
- Debouncing by `component_id` within 10 seconds.
- Raw signal storage even when debounced.
- Structured work item and RCA storage.
- RCA required before closure.
- MTTR calculation on RCA submission.
- Strategy pattern for alerting.
- State pattern for workflow transitions.
- `/health` endpoint.
- Throughput metrics printed every 5 seconds.
- Frontend live feed, detail view, raw signals, status transition controls, and RCA form.
- README architecture diagram and backpressure explanation.
- Sample data or simulation script.
- Tests for RCA validation.

## Current Verification Status

The following checks were run successfully:

```bash
cd backend
python3 -m pytest tests
```

Result:

```text
12 passed
```

Frontend build was also verified:

```bash
cd frontend
npm run build
```

Result:

```text
build succeeded
```

Smoke test result:

- Ingested 30 sample signals.
- Created one P0 RDBMS incident with 20 linked raw signals.
- Created one P1 MCP host incident with 10 linked raw signals.
- Confirmed closing a resolved incident without RCA returns a conflict error.
- Confirmed RCA submission followed by closure saves `mttr_seconds` on the work item.
- Authenticated 10,000-signal smoke test accepted and processed all 10,000 signals with zero drops.
- Added `scripts/load_test.py` with `--burst` for 50,000 signals over 5 seconds and scenario support such as `RDBMS_FLAP`.

## Suggested Next Improvements

If more time is available, improve the project in this order:

1. Add integration tests for ingestion debouncing.
2. Add persistent cache recovery from SQLite on startup.
3. Add pagination/search for raw signals.
4. Add WebSocket or Server-Sent Events instead of polling.
5. Add OpenTelemetry traces and Prometheus metrics.
6. Replace local stores with Dockerized Postgres, Redis, and ClickHouse.
7. Add authentication and responder ownership.
8. Add incident timeline comments and audit events.
