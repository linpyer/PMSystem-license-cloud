#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
load_environment
check_private_key
log "No separate signing-key registration CLI is required by this codebase."
log "At API startup, app.main derives the Ed25519 public key from the mounted private key and calls SigningKeyRepository.ensure_active_key."
log "The operation is idempotent for ${LICENSE_SIGNING_KEY_ID}; a conflicting keyId/public-key pair causes startup to fail safely."
if compose ps --status running license-api 2>/dev/null | grep -q license-api; then
  curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health/ready >/dev/null
  log "Readiness confirms the configured ACTIVE signing key matches the running signer."
else
  log "The key will be registered when license-api starts after migrations."
fi
