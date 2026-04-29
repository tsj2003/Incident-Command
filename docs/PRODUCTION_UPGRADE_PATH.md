# Production Upgrade Path

The local assessment profile is intentionally laptop-friendly. The production profile moves volatile hot-path state out of process and keeps the same application interfaces.

## Current Production Profile

Run:

```bash
docker compose -f docker-compose.production.yml up --build
```

This enables:

- Backend and frontend restart policies.
- Redis-backed dashboard cache when `REDIS_URL` is set.
- Redis-backed aggregation counters when `REDIS_URL` is set.
- Prometheus scraping `/metrics`.
- Persistent Docker volumes for SQLite/JSONL and Redis AOF.

## Next Production Replacements

- Source of Truth: replace SQLite with PostgreSQL using the same repository methods.
- Data Lake: replace local JSONL with S3, ClickHouse, or OpenSearch.
- Queue: replace in-process queue with Kafka, NATS, Pulsar, or Redpanda.
- Cache: Redis is already supported in the production compose profile.
- Metrics: Prometheus is already supported; add Grafana dashboards for review.

## Why Not Remove SQLite Entirely Here?

For the assignment, SQLite keeps the project runnable with one command and no external cloud dependencies. The code now separates repository/cache/aggregation boundaries so production infrastructure can be swapped without changing API or UI contracts.
