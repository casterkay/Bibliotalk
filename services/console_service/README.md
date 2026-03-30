# console_service (Bibliotalk Operator Console)

This is the operator/admin console UI for Bibliotalk, implemented as a Next.js app with same-origin `/api/*`
Route Handlers that proxy to backend services (primarily `memory_service`).

## Environment

- `BIBLIOTALK_ADMIN_TOKEN` (required): console login token and downstream admin bearer token.
- `MEMORIES_SERVICE_URL` (optional): defaults to `http://localhost:8080`.

## Local dev

From repo root:

```bash
npm --prefix services/console_service install
npm --prefix services/console_service run dev -- -H 0.0.0.0 -p 3000
```
