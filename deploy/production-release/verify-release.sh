#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
[[ $# -eq 4 ]] || die "${EXIT_DEPLOY}" "usage: $0 ARCHIVE SHA256 COMMIT STAGING"
archive="$1" expected_sha="${2,,}" expected_commit="$3" staging="$4"
[[ "${archive}" == "${DDREC_ROOT}/incoming/"* ]] || die "${EXIT_DEPLOY}" 'archive must be inside incoming'
[[ "${expected_sha}" =~ ^[0-9a-f]{64}$ ]] || die "${EXIT_DEPLOY}" 'invalid archive SHA256'
[[ "${expected_commit}" =~ ^[0-9a-f]{40}$ ]] || die "${EXIT_DEPLOY}" 'invalid expected commit'
[[ "${staging}" == "${DDREC_ROOT}/release/.staging-"* ]] || die "${EXIT_DEPLOY}" 'unsafe staging path'
require_file "${archive}"
actual_sha="$(sha256sum "${archive}" | awk '{print $1}')"
[[ "${actual_sha}" == "${expected_sha}" ]] || die "${EXIT_DEPLOY}" 'archive SHA256 mismatch'
[[ ! -e "${staging}" ]] || die "${EXIT_DEPLOY}" "staging already exists: ${staging}"
install -d -m 0750 "${staging}"
tar -xzf "${archive}" --strip-components=1 -C "${staging}"
for item in compose.yml SHA256SUMS.txt RELEASE-VERSION.txt RELEASE-GIT-COMMIT.txt admin scripts api-source/alembic/versions api-source/Dockerfile.offline-upgrade; do
  [[ -e "${staging}/${item}" ]] || die "${EXIT_DEPLOY}" "release item missing: ${item}"
done
wheel_count="$(find "${staging}/api-source" -maxdepth 1 -type f -name 'ddrec_license_server-*.whl' | wc -l | tr -d ' ')"
[[ "${wheel_count}" == 1 ]] || die "${EXIT_DEPLOY}" "release must contain exactly one API wheel: ${wheel_count}"
(cd "${staging}" && sha256sum -c SHA256SUMS.txt)
commit="$(tr -d '\r\n' <"${staging}/RELEASE-GIT-COMMIT.txt")"
[[ "${commit}" == "${expected_commit}" ]] || die "${EXIT_DEPLOY}" "release commit mismatch: ${commit}"
version="$(tr -d '\r\n' <"${staging}/RELEASE-VERSION.txt")"
[[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "${EXIT_DEPLOY}" 'invalid release version'
while IFS= read -r shell_file; do bash -n "${shell_file}"; done < <(find "${staging}/scripts" -type f -name '*.sh' -print)
if grep -RniE 'op\.drop_(table|column)[[:space:]]*\(|DROP[[:space:]]+(TABLE|COLUMN)|TRUNCATE[[:space:]]+|DELETE[[:space:]]+FROM' \
  "${staging}/api-source/alembic/versions" >"${staging}/DESTRUCTIVE-MIGRATIONS.txt" 2>/dev/null; then
  die "${EXIT_MIGRATION}" 'destructive migration pattern found; manual audit required'
fi
printf 'version=%s\ncommit=%s\nstaging=%s\n' "${version}" "${commit}" "${staging}"
