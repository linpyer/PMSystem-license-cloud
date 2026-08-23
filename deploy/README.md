# DDREC License Deployment

This directory contains deployment-only assets for the authorization service and administration
portal. It is deliberately excluded from the DDREC Windows installer.

- `production-nginx/`: official Linux production package for host Nginx, Dockerized API,
  and Dockerized PostgreSQL. Docker operations run on the production server, never on the Windows workstation.

Real environment files, keys, certificates, database volumes, and backups must remain outside Git.
The production environment must never connect to the DDREC business SQLite database.

## Unified cloud release builder

On Windows, double-click `一键打包-云端授权系统.bat` and choose the environment and component.
The menu delegates each production component to one implementation:

```powershell
scripts/build_cloud_release.ps1 -Environment production -Service api
scripts/build_cloud_release.ps1 -Environment production -Service admin
scripts/build_cloud_release.ps1 -Environment production -Service all
```

`api`, `admin`, and `all` artifacts are isolated under `artifacts/cloud/production/<service>`.
The production `all` package contains API source and wheel, the admin static site, Compose, Nginx,
migrations, and deployment/rollback helpers. It does not invoke local Docker or contain server
environment files or secrets. After explicit deployment approval, the production executor builds a
commit-specific API image on the server from the current production API image. The legacy
`production-nginx/build-production-release.ps1` entry now delegates to this unified implementation.

The repository root `VERSION` is the release version source. API and admin package metadata must
match it or the build stops. Production builds require branch `v1.3`, a clean worktree,
`https://license.aixcc.top/api/v1`, the `生产环境` label, and all security checks.

The former local authorization stack and local cloud build profile are retired and unsupported.
