# Prompt Record

The repository was created and refined through a series of iterative prompts to ensure 100% compliance with the assignment rubric. Below is the record of the key prompts used to create and harden this repository.

### Initial Assignment Prompt

> Engineering Challenge: Mission-Critical Incident Management System (IMS)
>
> Build a resilient IMS that ingests high-volume signals, debounces component failures, stores raw payloads separately from structured work items and RCA records, supports async processing, rate limiting, observability, incident workflow transitions, mandatory RCA before closure, MTTR calculation, and a responsive UI.

### Production Hardening & Architecture Prompt

> Task: Finalize and "harden" the Incident Management System (IMS) for a high-scale production environment.
> Objective: Ensure 100% compliance with the Zeotap assignment rubric with zero technical debt.
> 
> 1. Security & Data Integrity Layer: API Key Middleware, Signal Sanitization.
> 2. Advanced Observability & Metrics: Throughput Task, Prometheus Readiness, Health Checks.
> 3. Resilience & Graceful Shutdown: Retry Logic (@retry_on_failure), SIGTERM Handling.
> 4. Chaos & Performance Scripting: Load Test script with --burst and --scenario.
> 5. Professional Documentation: High-quality README, SRE rationale, MTTR math.

### UI & UX Polish Prompt

> https://wisprflow.ai front end must be like this. It still uses SQLite + in-memory cache/aggregations, which is acceptable for assignment scope but not truly production-scale. And implement this also, production grade ready. And all the points we have mentioned above which keep it from being in the top 0.01%. Create a plan and start implementing every point, each and every point, one by one, and it must be working.

### Architecture Diagram Generation Prompt

> I am thinking of putting the infrastructure or the system architecture we have used in this, so give a prompt for Gemini. I will give that and generate the image. It must be clear.

### Documentation Personalization Prompt

> Make sure that the README file must not look like AI-generated. It must look like that I have written as Tarandeep Singh Juneja, and tell me where to add the photo.

***

*Note: The implementation choices (like keeping JSONL/SQLite as default but providing a Redis production path) were made pragmatically to keep the project easily runnable on a local machine while strictly preserving the architectural boundaries expected in a mission-critical production environment.*
