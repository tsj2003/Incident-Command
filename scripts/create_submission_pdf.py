from __future__ import annotations

from pathlib import Path
from textwrap import wrap


OUTPUT = Path("Tarandeep Singh Juneja - Infrastructure SRE Intern Assignment.pdf")
GITHUB_LINK = "https://github.com/tsj2003/Incident-Command"

LINES = [
    "Tarandeep Singh Juneja - Infrastructure / SRE Intern Assignment",
    "",
    f"GitHub Repository: {GITHUB_LINK}",
    "",
    "Project: Mission-Critical Incident Management System (IMS)",
    "",
    "Summary",
    "This submission implements a resilient Incident Management System for high-volume distributed-stack signals across APIs, MCP hosts, caches, queues, RDBMS, and NoSQL stores. The system ingests signals asynchronously, applies API-key security and rate limiting, debounces noisy component failures, persists raw and structured data separately, exposes operational metrics, and provides a workflow-driven React dashboard with mandatory RCA before closure.",
    "",
    "How to run",
    "1. IMS_API_KEY=dev-secret docker compose -f docker-compose.production.yml up --build",
    "2. Open http://localhost:5173 for the dashboard.",
    "3. Open http://localhost:8000/health for health.",
    "4. Open http://localhost:9090/query for Prometheus.",
    "5. Seed data: cd backend && python3 scripts/simulate_failure.py --base-url http://localhost:8000 --api-key dev-secret --rate 1000 --duration 1 --batch-size 500",
    "",
    "Rubric coverage",
    "- Concurrency and scaling: FastAPI, asyncio workers, bounded queue of 25,000, batch flushing at 1,000 signals or 1 second, immediate 503 backpressure.",
    "- Data handling: JSONL raw signal audit log, SQLite source of truth, Redis-backed production hot cache and aggregation profile, in-memory local fallback.",
    "- LLD: Alerting Strategy pattern and Workflow State pattern.",
    "- UI/UX: React/Vite dashboard with live feed, detail view, raw signals, status workflow, RCA form, and audit timeline.",
    "- Resilience: exponential retry decorator for SQLite writes, graceful shutdown drain, health checks, Prometheus metrics, signal sanitization.",
    "- Testing: pytest suite covers alerting, RCA validation, batch processing, backpressure, sanitization, security, and health/metrics.",
    "- Documentation: README, benchmark report, production upgrade path, rubric mapping, screenshots guide, prompt/context/plan markdowns.",
    "",
    "MTTR formula",
    "MTTR = sum(Resolution Timestamp - Incident Start Timestamp) / Total Incidents Resolved",
    "",
    "Verification",
    "Backend tests: 13 passed. Frontend production build: successful.",
]


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_text(lines: list[str]) -> bytes:
    content = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    first = True
    for line in lines:
        wrapped = wrap(line, width=92) or [""]
        for segment in wrapped:
            if first:
                content.append(f"({pdf_escape(segment)}) Tj")
                first = False
            else:
                content.append(f"T* ({pdf_escape(segment)}) Tj")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


def main() -> None:
    OUTPUT.write_bytes(build_pdf_text(LINES))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
