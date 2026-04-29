# Build Plan

1. Implement an async ingestion API with a bounded in-memory queue, bulk ingestion, fixed-window rate limiting, API-key security, and console pulse metrics.
2. Split persistence by workload: JSONL document log for raw signals, SQLite transactional source of truth for work items/RCA, in-memory dashboard cache, and minute-level timeseries aggregation.
3. Model failure mediation with design patterns: Strategy for alert severity/channel selection and State for incident lifecycle transitions.
4. Build a responsive React dashboard with live incident feed, detail view, raw signal list, status controls, and mandatory RCA form.
5. Add tests for RCA validation and closure enforcement, sample failure data, Docker Compose, and documentation.
