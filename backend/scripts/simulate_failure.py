from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import datetime, timezone

import httpx


def make_signal(component_id: str, component_type: str, idx: int) -> dict:
    service = "orders-platform" if component_type == "RDBMS" else "agent-runtime"
    return {
        "component_id": component_id,
        "component_type": component_type,
        "service": service,
        "error_code": "CONNECTION_TIMEOUT" if component_type == "RDBMS" else "HOST_UNREACHABLE",
        "message": f"{component_id} failure sample {idx}",
        "latency_ms": 4_500 if component_type == "RDBMS" else 1_200,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"sample": True, "sequence": idx, "trace_id": f"trace-{component_id}-{idx}"},
    }


def build_batch(offset: int, size: int) -> list[dict]:
    signals: list[dict] = []
    for idx in range(offset, offset + size):
        if idx % 3 == 0:
            signals.append(make_signal("MCP_HOST_EAST_02", "MCP_HOST", idx))
        else:
            signals.append(make_signal("RDBMS_PRIMARY_01", "RDBMS", idx))
    return signals


async def post_batch(client: httpx.AsyncClient, base_url: str, api_key: str, offset: int, size: int) -> int:
    response = await client.post(
        f"{base_url}/signals/bulk",
        json=build_batch(offset, size),
        headers={
            "X-API-KEY": api_key,
            "Authorization": f"Bearer {api_key}",
            "x-forwarded-for": f"10.10.{(offset // size) % 255}.10",
        },
    )
    response.raise_for_status()
    body = response.json()
    return int(body["accepted"])


async def main() -> None:
    parser = argparse.ArgumentParser(description="Drive IMS ingestion at a target signal rate.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=os.getenv("IMS_API_KEY", "dev-secret"))
    parser.add_argument("--rate", type=int, default=10_000, help="Target signals per second.")
    parser.add_argument("--duration", type=int, default=5, help="Load-test duration in seconds.")
    parser.add_argument("--batch-size", type=int, default=1_000, help="Signals per bulk request.")
    args = parser.parse_args()

    accepted = 0
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=20) as client:
        for second in range(args.duration):
            second_started = time.perf_counter()
            batches = max(1, args.rate // args.batch_size)
            tasks = [
                post_batch(client, args.base_url, args.api_key, second * args.rate + idx * args.batch_size, args.batch_size)
                for idx in range(batches)
            ]
            accepted += sum(await asyncio.gather(*tasks))

            elapsed = time.perf_counter() - second_started
            if elapsed < 1:
                await asyncio.sleep(1 - elapsed)

    total_elapsed = time.perf_counter() - started
    print(
        {
            "accepted": accepted,
            "elapsed_seconds": round(total_elapsed, 3),
            "observed_signals_per_second": round(accepted / total_elapsed, 2),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
