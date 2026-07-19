#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
[[ -t 0 && -t 1 ]] || fail "OWNER creation requires an interactive server terminal"
[[ $# -eq 2 ]] || fail "Usage: $0 USERNAME DISPLAY_NAME"
username="$1"
display_name="$2"
[[ "${username}" != "admin" && ${#username} -ge 4 ]] || fail "Use a non-default username with at least four characters"
[[ -n "${display_name}" ]] || fail "Display name is required"
load_environment
wait_for_health license-api 20
log "The CLI will prompt securely for a strong password and display TOTP enrollment once."
compose exec license-api python -m app.cli.create_admin \
  --username "${username}" --display-name "${display_name}" --role OWNER
log "Store TOTP enrollment information in approved offline secret storage; it is not logged by this script."
