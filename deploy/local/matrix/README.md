# Local Matrix Dev Stack (Synapse + Element)

This directory hosts a **local-only** Matrix stack for Bibliotalk development:

- Synapse homeserver (`http://localhost:8008`)
- Element Web client (`http://localhost:8081`)

## Quick start

Use the helper script from repo root:

```bash
./scripts/matrix-dev.sh up
```

This will:

1) generate `deploy/local/matrix/.env` (gitignored) if missing
2) generate `deploy/local/matrix/appservice/bibliotalk.local.yaml` (gitignored)
3) generate `deploy/local/matrix/element/config.json` (gitignored)
4) generate Synapse config `deploy/local/matrix/synapse/data/homeserver.yaml` (first run only)
5) generate Synapse overrides `deploy/local/matrix/synapse/data/homeserver.local.yaml` (gitignored by directory ignore)
6) `docker compose up -d` Synapse + Element
7) provision an admin user and a `Bibliotalk` Space + `General` room (idempotent)

## Files

- `docker-compose.yml`: Synapse + Element Web
- `appservice/bibliotalk.example.yaml`: appservice registration template (no secrets)
- `element/config.example.json`: Element config template

## Notes

- This stack is not intended for production (Synapse uses SQLite by default).
- The appservice registration points at `MATRIX_APPSERVICE_URL` (defaults to `http://host.docker.internal:9009`) for a locally-run `matrix_service`.
- Synapse is started with multiple config files (`homeserver.yaml` + `homeserver.local.yaml`) to avoid editing the generated Synapse config.
- If Synapse crashes with a proxy parsing error (e.g. `Port could not be cast to integer value as b'port'`), set `MATRIX_HTTP_PROXY=` and `MATRIX_HTTPS_PROXY=` in `deploy/local/matrix/.env` (or fix your Docker global proxy settings).
