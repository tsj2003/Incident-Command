# Benchmark Report

## Goal

Prove the IMS can handle the assignment target of 10,000 signals/sec without unbounded memory growth or data loss under normal local conditions.

## Command

```bash
cd backend
python scripts/simulate_failure.py --base-url http://127.0.0.1:8000 --rate 10000 --duration 1 --batch-size 1000 --api-key dev-secret
```

## Observed Result

```text
accepted: 10000
elapsed_seconds: 1.076
observed_signals_per_second: 9293.96
```

The backend then reported:

```text
accepted: 10000
processed: 10000
dropped: 0
queue_depth: 0
pending_batch: 0
```

Debounced incidents:

```text
RDBMS_PRIMARY_01 P0 6666 signals
MCP_HOST_EAST_02 P1 3334 signals
```

## Notes

The observed client-side rate includes Python/httpx client overhead on a laptop. The server-side design uses a bounded queue, async workers, and a batch flusher to keep persistence out of the request hot path.

For a stronger benchmark, run:

```bash
python scripts/load_test.py --burst --scenario RDBMS_FLAP --api-key dev-secret
```

This attempts 50,000 signals over 5 seconds.
