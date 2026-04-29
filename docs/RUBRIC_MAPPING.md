# Zeotap Rubric Mapping

| Rubric Area | Evidence |
| --- | --- |
| Concurrency & Scaling | `backend/app/ingestion.py` uses `asyncio.Queue(maxsize=25000)`, async workers, atomic bulk admission, per-component debounce locks, and immediate `503` on saturation. |
| Data Handling | `backend/app/storage.py` separates JSONL raw audit log, SQLite source of truth, dashboard cache, and aggregation sink. Production compose enables Redis-backed cache/aggregations through `REDIS_URL`. |
| LLD | Strategy pattern in `backend/app/alerting.py`; State pattern in `backend/app/workflow.py`; Pydantic and SQLAlchemy Core schemas in `backend/app/models.py`; retry decorator in `backend/app/storage.py`. |
| UI/UX & Integration | React dashboard in `frontend/src/main.jsx` with live feed, incident detail, raw signals, audit timeline, status workflow, and RCA form. |
| Resilience & Testing | Exponential retry for SQLite writes, graceful shutdown drain, API key middleware, sanitization tests, RCA validation tests, batch/backpressure tests, metrics/health tests. |
| Documentation | `README.md`, `docs/CONTEXT.md`, `docs/PLAN.md`, `docs/PROMPTS.md`, `docs/BENCHMARK.md`, and this mapping. |
| Tech Stack Choices | FastAPI/asyncio for ingestion, JSONL for append-only raw lake, SQLite for local source of truth, Redis in production profile for hot cache/aggregations, React/Vite UI, Docker Compose. |

## Submission Checklist

- `/backend` and `/frontend` exist.
- Docker Compose included.
- Architecture diagram included.
- Backpressure explanation included.
- Sample data and load scripts included.
- Prompts/spec/plans checked in.
- Tests pass locally.
