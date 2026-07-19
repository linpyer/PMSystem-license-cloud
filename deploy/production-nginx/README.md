# PMSystem License Production Offline Deployment

This package deploys the PMSystem licensing API and PostgreSQL with Docker while host Nginx serves the Vue admin application. The server does not need Internet access to Docker Hub and does not run Caddy or a Vite development server.

## Verified application entry points

- API image command: `uvicorn app.main:app --host 0.0.0.0 --port 8080`
- Database migration: `alembic upgrade head`
- Initial OWNER: `python -m app.cli.create_admin --username ... --display-name ... --role OWNER`
- Liveness: `/api/v1/health/live`
- Readiness: `/api/v1/health/ready`

The API startup lifespan derives the Ed25519 public key from the mounted private key and calls `SigningKeyRepository.ensure_active_key`. There is no separate public-key import CLI. A new key is registered idempotently; a reused keyId with different public material fails startup. Readiness verifies that the database ACTIVE key and mounted signer agree.

## Offline package installation

Upload both the release archive and its `.sha256.txt` file to the server. Then run:

```bash
cd /opt/pmsystem-license
sha256sum -c PMSystem-License-Production-1.0.5.tar.gz.sha256.txt
mkdir -p /opt/pmsystem-license/release/1.0.5
tar -xzf PMSystem-License-Production-1.0.5.tar.gz \
  --strip-components=1 \
  -C /opt/pmsystem-license/release/1.0.5
cd /opt/pmsystem-license/release/1.0.5

bash scripts/precheck.sh
bash scripts/load-images.sh
bash scripts/init-production.sh
bash scripts/install-release.sh "$PWD"
bash scripts/migrate.sh        # starts PostgreSQL only, then applies Alembic head
bash scripts/start.sh
bash scripts/register-signing-key.sh
bash scripts/verify.sh
```

For a new installation, the ordered wrapper can be used after images and secrets exist:

```bash
bash scripts/deploy.sh "$PWD"
```

`deploy.sh` refuses to continue if `.env.production` or the production private key is absent. `init-production.sh` generates those secrets only on the server and refuses to overwrite existing material by default.

The private key is installed as `root:10001` with mode `640`. Initialization and deployment start a short-lived API image process explicitly as `10001:10001` and read the bind-mounted key bytes without printing them. A failed read stops initialization or deployment. The key is never made world-readable, and the long-running API container remains non-root.

Create the first OWNER interactively after the API is ready:

```bash
bash /opt/pmsystem-license/current/scripts/create-owner.sh owner_name "System Owner"
```

The password prompt and one-time TOTP enrollment output must be handled only in the secure server terminal and saved in approved offline secret storage.

## Nginx and HTTPS

The initial file `/etc/nginx/conf.d/pmsystem-license.conf` serves:

- `http://license.aixcc.top/admin/`
- `http://license.aixcc.top/api/v1/`

It redirects `/` to `/admin/`, provides Vue history fallback, serves hashed assets directly, and proxies the API to `127.0.0.1:8080` without rewriting `/api/v1`. Existing Nginx configuration is never overwritten; a changed packaged file is installed as `.conf.new`.

After DNS and HTTP validation, install and run the distribution-supported Certbot Nginx integration manually, for example:

```bash
certbot --nginx -d license.aixcc.top
nginx -t && systemctl reload nginx
curl -fsS https://license.aixcc.top/api/v1/health/live
curl -fsS https://license.aixcc.top/api/v1/health/ready
```

Review Certbot's changes and the TLS policy before enabling production traffic.

## Exporting the production public key

Only the public key may be copied from:

```text
/opt/pmsystem-license/secrets/production_ed25519_public.pem
```

The Windows production client must trust `production-2026-01` and the matching public key before release. The production private key must never be downloaded to an ordinary workstation, copied into the Windows client, committed to Git, included in this package, or sent through chat.

## Operations

```bash
bash /opt/pmsystem-license/current/scripts/status.sh
bash /opt/pmsystem-license/current/scripts/verify.sh
bash /opt/pmsystem-license/current/scripts/backup.sh
bash /opt/pmsystem-license/current/scripts/backup.sh 30
bash /opt/pmsystem-license/current/scripts/restart.sh
bash /opt/pmsystem-license/current/scripts/stop.sh
```

`backup.sh` creates a PostgreSQL custom-format dump and SHA-256 file without stopping the database. Retention deletion occurs only when an explicit positive day count is supplied and only inside `/opt/pmsystem-license/backups`.

## Updating

1. Run `backup.sh` and verify its checksum.
2. Upload and verify the new release archive.
3. Extract it into a new `/opt/pmsystem-license/release/<version>` directory.
4. Run the new `load-images.sh`.
5. Run `install-release.sh` to switch `current` and deploy admin assets.
6. Review any generated Nginx `.conf.new` file.
7. Run `migrate.sh`.
8. Run `restart.sh`, then `verify.sh`.

Old images, releases, backups and the PostgreSQL named volume are retained.

## Rollback boundary

Application rollback can switch `/opt/pmsystem-license/current` back to a compatible old release and run that release's `restart.sh`. Database migrations may be irreversible; inspect migration compatibility before rolling back application code. The scripts never run `alembic downgrade`, never delete the production volume, and never use `docker compose down -v`.

## Security notes

- PostgreSQL has no host port mapping.
- The API binds only to host loopback `127.0.0.1:8080`.
- Both images use immutable version tags and `pull_policy: never`.
- The API runs as UID/GID 10001, with a read-only root filesystem, `/tmp` tmpfs and a read-only private-key mount.
- Production secrets live only in `/opt/pmsystem-license/config` and `/opt/pmsystem-license/secrets`; the signing key is exactly `root:10001` mode `640` and is mounted read-only.
- Production OpenAPI is disabled, cookies are Secure, origins and hosts are explicit, and request rate limiting is enabled.
