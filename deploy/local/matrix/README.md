# Local Matrix Dev Stack (Synapse + Element + MatrixRTC)

This directory hosts a **local-only** Matrix stack for Bibliotalk development:

- Synapse homeserver (`http://localhost:8008`)
- Element Web client (`http://localhost:8081`)
- Element Call (`http://localhost:9011`) for MatrixRTC calls
- LiveKit SFU (host ports `7880/tcp`, `7881/udp`, `50100-50200/udp`)
- lk-jwt-service (MatrixRTC Authorization Service; proxied under `http://localhost/livekit/jwt`)
- `/.well-known/matrix/client` server (host port `80`) for MatrixRTC focus discovery

## Quick start

Use the helper script from repo root:

```bash
./scripts/matrix-dev.sh up
```

This will:

1) generate `deploy/local/matrix/.env` (gitignored) if missing
2) generate `deploy/local/matrix/appservice/bibliotalk.local.yaml` (gitignored)
3) generate `deploy/local/matrix/element/config.json` (gitignored)
4) generate `deploy/local/matrix/element_call/config.json` (gitignored)
5) generate Synapse config `deploy/local/matrix/synapse/data/homeserver.yaml` (first run only)
6) generate Synapse overrides `deploy/local/matrix/synapse/data/homeserver.local.yaml` (gitignored by directory ignore)
7) `docker compose up -d` Synapse + Element + Element Call + LiveKit + lk-jwt-service + well-known
8) provision an admin user and a `Bibliotalk` Space + `General` room (idempotent)

## Files

- `docker-compose.yml`: Synapse + Element Web + MatrixRTC (Element Call + LiveKit)
- `appservice/bibliotalk.example.yaml`: appservice registration template (no secrets)
- `element/config.example.json`: Element config template
- `well-known/site/.well-known/matrix/client`: MatrixRTC focus discovery payload for `localhost`

## Notes

- This stack is not intended for production (Synapse uses SQLite by default).
- The appservice registration points at `MATRIX_APPSERVICE_URL` (defaults to `http://host.docker.internal:9009`) for a locally-run `matrix_service`.
- Synapse is started with multiple config files (`homeserver.yaml` + `homeserver.local.yaml`) to avoid editing the generated Synapse config.
- If Synapse crashes with a proxy parsing error (e.g. `Port could not be cast to integer value as b'port'`), set `MATRIX_HTTP_PROXY=` and `MATRIX_HTTPS_PROXY=` in `deploy/local/matrix/.env` (or fix your Docker global proxy settings).

- MatrixRTC discovery:
  - Element Call fetches `http://localhost/.well-known/matrix/client` because `MATRIX_SERVER_NAME=localhost`.
  - The `well-known` container binds host port `80` by default; change `WELL_KNOWN_PORT` if you already have something on port 80.
