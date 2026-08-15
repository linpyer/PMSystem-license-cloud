#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker sha256sum grep; do require_command "${command_name}"; done
image_tar="$(find "${RELEASE_ROOT}/images" -maxdepth 1 -type f -name 'ddrec-production-images-*.tar' -print -quit)"
[[ -n "${image_tar}" ]] || fail "Offline image archive was not found"
checksum_line="$(grep -F "  images/$(basename "${image_tar}")" "${RELEASE_ROOT}/SHA256SUMS.txt" || true)"
[[ -n "${checksum_line}" ]] || fail "Image archive checksum is missing"
(cd "${RELEASE_ROOT}" && printf '%s\n' "${checksum_line}" | sha256sum -c -)

docker load --input "${image_tar}"
version="$(tr -d '\r\n' < "${RELEASE_ROOT}/RELEASE-VERSION.txt")"
for image in "ddrec-license-api:${version}-production" "postgres:17.5-alpine"; do
  docker image inspect "${image}" >/dev/null 2>&1 || fail "Loaded archive does not contain ${image}"
  platform="$(docker image inspect "${image}" --format '{{.Os}}/{{.Architecture}}')"
  [[ "${platform}" == "linux/amd64" ]] || fail "${image} has unsupported platform ${platform}"
  log "Loaded ${image} (${platform})"
done
log "Images loaded locally. No registry pull was performed."
