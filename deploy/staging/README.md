# Staging Environment

The staging stack uses Compose project `ddrec-license-staging`, database
`ddrec_license_staging`, its own named volumes, an isolated Ed25519 key, and Caddy on port 18088.
It never reuses production secrets or the production database.

1. Copy each `env/*.example` file to the same name without `.example` and replace placeholders.
2. Generate a staging-only key under `secrets/dev_ed25519_private.pem`.
3. Run `docker compose run --rm license-api alembic upgrade head` explicitly.
4. Run `docker compose up -d` and open `http://127.0.0.1:18088/admin/`.

The `env/*.env` files and `secrets/` directory are ignored. Do not use `docker compose down -v`.
