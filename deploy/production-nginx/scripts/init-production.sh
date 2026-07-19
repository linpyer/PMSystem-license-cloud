#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker openssl install grep sed; do require_command "${command_name}"; done

force=false
if [[ "${1:-}" == "--force" ]]; then force=true; elif [[ -n "${1:-}" ]]; then fail "Usage: $0 [--force]"; fi

private_key="${PMSYSTEM_ROOT}/secrets/production_ed25519_private.pem"
public_key="${PMSYSTEM_ROOT}/secrets/production_ed25519_public.pem"
if [[ -e "${ENV_FILE}" || -e "${private_key}" || -e "${public_key}" ]]; then
  ${force} || fail "Production configuration or signing keys already exist; refusing to overwrite"
  [[ -t 0 ]] || fail "--force requires an interactive terminal"
  printf 'Type OVERWRITE-PRODUCTION-SECRETS to continue: '
  read -r confirmation
  [[ "${confirmation}" == "OVERWRITE-PRODUCTION-SECRETS" ]] || fail "Confirmation did not match"
  log "WARNING: replacing an in-use signing key invalidates the trust chain and requires a documented key rotation"
fi

release_version="$(grep -E '^PMSYSTEM_API_IMAGE_TAG=' "${RELEASE_ROOT}/env.production.example" | cut -d= -f2-)"
service_version="$(grep -E '^LICENSE_SERVICE_VERSION=' "${RELEASE_ROOT}/env.production.example" | cut -d= -f2-)"
build_commit="$(tr -d '\r\n' < "${RELEASE_ROOT}/BUILD-COMMIT.txt")"
[[ -n "${release_version}" && -n "${service_version}" && -n "${build_commit}" ]] || fail "Release metadata is incomplete"
api_image="pmsystem-license-api:${release_version}"
docker image inspect "${api_image}" >/dev/null 2>&1 || fail "Load ${api_image} before initialization"

install -d -m 750 "${PMSYSTEM_ROOT}" "${PMSYSTEM_ROOT}/release" "${PMSYSTEM_ROOT}/backups" "${PMSYSTEM_ROOT}/scripts"
install -d -m 700 "${PMSYSTEM_ROOT}/config" "${PMSYSTEM_ROOT}/secrets"

database_password="$(openssl rand -hex 32)"
session_secret="$(openssl rand -hex 32)"
code_pepper="$(openssl rand -hex 32)"
credential_pepper="$(openssl rand -hex 32)"
totp_key="$(docker run --rm --pull never --entrypoint python "${api_image}" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode("ascii"))')"
[[ -n "${totp_key}" ]] || fail "Could not generate the TOTP encryption key"

openssl genpkey -algorithm ED25519 -out "${private_key}"
openssl pkey -in "${private_key}" -pubout -out "${public_key}"
chown root:10001 "${private_key}"
chmod 640 "${private_key}"
chown root:root "${public_key}"
chmod 644 "${public_key}"

temporary_env="${ENV_FILE}.tmp.$$"
cat >"${temporary_env}" <<EOF
PMSYSTEM_API_IMAGE_TAG=${release_version}
POSTGRES_DB=pmsystem_license
POSTGRES_USER=pmsystem_license
POSTGRES_PASSWORD=${database_password}
LICENSE_DATABASE_URL=postgresql+asyncpg://pmsystem_license:${database_password}@postgres:5432/pmsystem_license
LICENSE_ENVIRONMENT=production
LICENSE_API_HOST=0.0.0.0
LICENSE_API_PORT=8080
LICENSE_PUBLIC_BASE_URL=https://license.aixcc.top
LICENSE_ADMIN_BASE_URL=https://license.aixcc.top/admin/
LICENSE_ADMIN_ALLOWED_ORIGINS=https://license.aixcc.top
LICENSE_ADMIN_COOKIE_NAME=pms_admin_session
LICENSE_ADMIN_COOKIE_SECURE=true
LICENSE_ADMIN_SESSION_SECRET=${session_secret}
LICENSE_ADMIN_TOTP_ENCRYPTION_KEY=${totp_key}
LICENSE_ADMIN_SESSION_IDLE_MINUTES=30
LICENSE_ADMIN_SESSION_MAX_HOURS=8
LICENSE_ADMIN_LOGIN_MAX_FAILURES=5
LICENSE_ADMIN_LOCKOUT_MINUTES=15
LICENSE_ALLOWED_HOSTS=license.aixcc.top,127.0.0.1,localhost
LICENSE_TRUSTED_PROXY_COUNT=1
LICENSE_CODE_PEPPER=${code_pepper}
LICENSE_DEVICE_CREDENTIAL_PEPPER=${credential_pepper}
LICENSE_SIGNING_KEY_ID=production-2026-01
LICENSE_SIGNING_PRIVATE_KEY_PATH=/run/secrets/license_signing_private_key.pem
LICENSE_MINIMUM_CLIENT_VERSION=1.0.5
LICENSE_LOG_LEVEL=INFO
LICENSE_OPENAPI_ENABLED=false
LICENSE_RATE_LIMIT_ENABLED=true
LICENSE_REQUEST_MAX_BYTES=10485760
LICENSE_DB_POOL_SIZE=5
LICENSE_DB_MAX_OVERFLOW=5
LICENSE_DB_POOL_TIMEOUT_SECONDS=10
LICENSE_DB_STATEMENT_TIMEOUT_MS=15000
LICENSE_BACKUP_RETENTION_DAYS=30
LICENSE_BUILD_COMMIT=${build_commit}
LICENSE_SERVICE_VERSION=${service_version}
EOF
chmod 600 "${temporary_env}"
mv -f "${temporary_env}" "${ENV_FILE}"
export PMSYSTEM_API_IMAGE_TAG="${release_version}"
verify_private_key_readable
log "Production configuration and Ed25519 key pair were created without printing secret material."
log "Public key: ${public_key}"
log "Back up the private key offline in encrypted storage. Never copy it into the client or release bundle."
