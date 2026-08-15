# DDREC License Deployment

This directory contains deployment-only assets for the authorization service and administration
portal. It is deliberately excluded from the DDREC Windows installer.

- `production-nginx/`: official offline Linux production package for host Nginx, Dockerized API,
  and Dockerized PostgreSQL. The server never pulls images from a registry.
- `staging/`: isolated local or non-production simulation with separate database, volume, keys,
  administrator, cookie name, and HTTP port.

Real environment files, keys, certificates, database volumes, and backups must remain outside Git.
Neither environment may connect to the DDREC business SQLite database.

## Unified cloud release builder

On Windows, double-click `一键打包-云端授权系统.bat` and choose the environment and component.
The menu delegates every combination to one implementation:

```powershell
scripts/build_cloud_release.ps1 -Environment local -Service api
scripts/build_cloud_release.ps1 -Environment production -Service admin
scripts/build_cloud_release.ps1 -Environment production -Service all -ExportDockerImage
```

`api`, `admin`, and `all` artifacts are isolated under `artifacts/cloud/<environment>/<service>`.
The production `all` package contains API source, the admin static site, Compose, Nginx, migrations,
and deployment/rollback helpers. Add `-ExportDockerImage` when creating the fully offline production
package used by `/opt/ddrec-license`; this exports immutable `linux/amd64` API and PostgreSQL
images without embedding any server environment file or secret. The legacy
`production-nginx/build-production-release.ps1` entry now delegates to this unified implementation.

The repository root `VERSION` is the release version source. API and admin package metadata must
match it or the build stops. Production builds require branch `v1.3`, a clean worktree,
`https://license.aixcc.top/api/v1`, the `生产环境` label, and all security checks.
