# Screenshots and Demo Capture

The frontend has been redesigned in a Wispr Flow-inspired style: warm off-white background, dark ink outlines, rounded product panels, soft yellow/blue accents, and an operational command-center layout.

To capture screenshots:

1. Start the stack:

```bash
docker compose up --build
```

2. Seed data:

```bash
cd backend
python scripts/simulate_failure.py --api-key dev-secret --rate 10000 --duration 1
```

3. Open:

```text
http://localhost:5173
```

Recommended screenshots:

- Live feed with P0/P1 incidents.
- Incident detail with RCA form.
- Incident timeline after status transitions.
- `/health` response.
- `/metrics` response.
