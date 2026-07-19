# Disaster Recovery

## First Principles

Stop writes, preserve evidence, and record UTC timestamps. Validate every backup in an isolated
temporary database before any cutover. Verify SHA-256, Alembic version, critical tables, record
counts, the ACTIVE signing key, and the mounted private key. Never run `docker compose down -v`.

`verify-backup.sh` creates and removes an isolated verification database. `restore-postgres.sh`
requires an explicit `pmsystem_license_restore_*` database name, never overwrites the configured
production database, and retains a successful temporary restore for review. Production replacement
is always a separate, documented manual operation.

## Scenarios

- **Server loss:** provision a clean supported Linux host, load reviewed offline images, restore the
  server-owned environment and signing key from encrypted backups, validate the database in a
  temporary database, configure host Nginx and Certbot, then switch traffic after health checks.
- **PostgreSQL volume damage:** leave the damaged volume untouched for forensics. Create a new volume,
  validate a backup in a temporary database, and check Alembic and signing-key consistency before a
  reviewed cutover.
- **Accidental record deletion:** stop write traffic and restore a backup from before the event into
  a temporary database. Prefer a reviewed data repair transaction; replacing the whole database may
  discard newer audit, activation, and device state.
- **Private key lost:** never generate different key material under the same keyId. Recover the
  encrypted offline copy or perform a documented key rotation and client trust-set release.
- **Private key leaked:** revoke access, preserve evidence, create a new keyId, publish a client that
  trusts the required transition keys, switch issuance, retire the compromised key, and assess
  whether licenses must be reissued.
- **Administrator recovery:** use the local password reset CLI from a secured server terminal, revoke
  other sessions, and review audit history. TOTP recovery must not expose secrets through the web UI.
- **Domain or certificate failure:** inspect DNS, host Nginx, Certbot state, clock sync, and firewall
  rules for 80/443. Keep ports 5432 and 8080 private and never bypass TLS in production clients.
- **Admin portal unavailable:** test `/admin/`, liveness, and readiness independently; validate the
  Nginx SPA fallback and immutable static assets before changing application state.
- **Failed deployment:** switch `/opt/pmsystem-license/current` back to a compatible retained release
  and run its `restart.sh`. Never run automatic Alembic downgrade; prefer a forward fix unless a
  migration-specific recovery plan has been reviewed.
- **Corrupt backup:** reject it on checksum or restore failure, preserve it for investigation, and
  validate the next newest local or off-site backup.
- **Clients holding old licenses:** keep required old public keys in client trust sets through key
  rotation. Database restoration may require reconciliation of status changes made after the backup.

After recovery, rotate exposed credentials, create and verify a fresh backup, review administrator
and license audit events, and document the incident. Database signing-key records and mounted private
key material must always describe the same ACTIVE keyId.
