# Prompt Record

The repository was created from the assignment prompt:

> Engineering Challenge: Mission-Critical Incident Management System (IMS)
>
> Build a resilient IMS that ingests high-volume signals, debounces component failures, stores raw payloads separately from structured work items and RCA records, supports async processing, rate limiting, observability, incident workflow transitions, mandatory RCA before closure, MTTR calculation, and a responsive UI.

Implementation choices were made to keep the project runnable on a laptop while preserving the architecture boundaries expected in production:

- FastAPI async ingress and workers.
- Bounded queue for backpressure.
- JSONL raw audit sink, SQLite source-of-truth sink, in-memory hot dashboard cache, and in-memory timeseries aggregation sink.
- React/Vite dashboard.
