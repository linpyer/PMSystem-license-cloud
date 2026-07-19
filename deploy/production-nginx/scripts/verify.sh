#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
for command_name in curl nginx ss; do require_command "${command_name}"; done
load_environment
wait_for_health postgres 20
wait_for_health license-api 20
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health/live >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health/ready >/dev/null
require_file /var/www/pmsystem-license/admin/index.html
nginx -t

if ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq '(^|\]|:|\*)0\.0\.0\.0:5432$|\[::\]:5432$|\*:5432$'; then
  fail "PostgreSQL is listening publicly on 5432"
fi
api_listeners="$(ss -lnt | awk 'NR > 1 && $4 ~ /:8080$/ {print $4}')"
[[ -n "${api_listeners}" ]] || fail "No API listener was found on 8080"
if printf '%s\n' "${api_listeners}" | grep -Evq '^(127\.0\.0\.1|\[::1\]):8080$'; then
  fail "API port 8080 is not restricted to loopback"
fi

curl --fail --silent --show-error -H 'Host: license.aixcc.top' http://127.0.0.1/admin/ >/dev/null
curl --fail --silent --show-error -H 'Host: license.aixcc.top' http://127.0.0.1/api/v1/health/ready >/dev/null
if curl --fail --silent --show-error --connect-timeout 5 https://license.aixcc.top/api/v1/health/live >/dev/null 2>&1; then
  log "HTTPS health check succeeded"
else
  log "HTTPS is not active or not reachable yet; complete Certbot after HTTP and DNS validation"
fi
log "Production service verification passed."
