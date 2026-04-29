from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx


def signal(component_id: str, component_type: str, idx: int, status_hint: str = "ERROR") -> dict[str, Any]:
    return {
        "component_id": component_id,
        "component_type": component_type,
        "service": "orders-platform" if component_type == "RDBMS" else "agent-runtime",
        "error_code": "CONNECTION_TIMEOUT" if status_hint == "ERROR" else "RECOVERY_SIGNAL",
        "message": f"{component_id} {status_hint.lower()} sample {idx} from 10.1.2.{idx % 255}",
        "latency_ms": 4_500 if status_hint == "ERROR" else 80,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "scenario": status_hint,
            "sequence": idx,
            "trace_id": f"trace-{component_id}-{idx}",
            "authorization": "Bearer super-secret-token",
            "internal_ip": f"192.168.10.{idx % 255}",
        },
    }


def build_scenario_batch(scenario: str, offset: int, size: int) -> list[dict[str, Any]]:
    if scenario == "RDBMS_FLAP":
        return [
            signal("RDBMS_PRIMARY_01", "RDBMS", idx, "ERROR" if idx % 2 == 0 else "RESOLVED")
            for idx in range(offset, offset + size)
        ]
    if scenario == "MCP_OUTAGE":
        return [signal("MCP_HOST_EAST_02", "MCP_HOST", idx) for idx in range(offset, offset + size)]
    return [
        signal("RDBMS_PRIMARY_01", "RDBMS", idx) if idx % 3 else signal("CACHE_CLUSTER_01", "CACHE", idx)
        for idx in range(offset, offset + size)
    ]


async def post_batch(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    scenario: str,
    offset: int,
    batch_size: int,
) -> int:
    response = await client.post(
        f"{base_url}/signals/bulk",
        json=build_scenario_batch(scenario, offset, batch_size),
        headers={"X-API-KEY": api_key, "x-forwarded-for": f"10.20.{(offset // batch_size) % 255}.5"},
    )
    response.raise_for_status()
    return int(response.json()["accepted"])


async def run() -> None:
    parser = argparse.ArgumentParser(description="IMS chaos and performance load driver.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=os.getenv("IMS_API_KEY", "dev-secret"))
    parser.add_argument("--scenario", choices=["RDBMS_FLAP", "MCP_OUTAGE", "MIXED_STACK"], default="MIXED_STACK")
    parser.add_argument("--burst", action="store_true", help="Send 50,000 signals over 5 seconds.")
    parser.add_argument("--signals", type=int, default=10_000)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=1_000)
    args = parser.parse_args()

    total_signals = 50_000 if args.burst else args.signals
    duration = 5 if args.burst else args.duration
    batches = max(1, total_signals // args.batch_size)
    batch_offsets = [idx * args.batch_size for idx in range(batches)]
    accepted = 0
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=30) as client:
        for second in range(duration):
            second_started = time.perf_counter()
            offsets = batch_offsets[second::duration]
            tasks = [
                post_batch(client, args.base_url, args.api_key, args.scenario, offset, args.batch_size)
                for offset in offsets
            ]
            if tasks:
                accepted += sum(await asyncio.gather(*tasks))
            elapsed = time.perf_counter() - second_started
            if elapsed < 1:
                await asyncio.sleep(1 - elapsed)

    elapsed = time.perf_counter() - started
    print(
        {
            "scenario": args.scenario,
            "accepted": accepted,
            "elapsed_seconds": round(elapsed, 3),
            "observed_tps": round(accepted / elapsed, 2),
            "burst": args.burst,
        }
    )


if __name__ == "__main__":
    asyncio.run(run())
