# Cloud Legacy Client Dependency Map

Scope: the historical desktop-client copy rooted at `cloud-license/app`, plus its root `main.py`.
This map is read-only Batch 1 evidence. It does not authorize deletion of the copy or its build files.

## Dependency classification

| Consumer or entrypoint | Classification | Evidence |
|---|---|---|
| Current iVRec Release | `no dependency` | `scripts/release/DDREC.Release.psm1` retains its internal historical module name but resolves `ClientRoot` to the sibling workspace `client` repository. Current iVRec artifacts and update public keys are read from that repository, not from `cloud-license/app`. |
| Current Cloud Build | `no dependency` | `scripts/build_cloud_release.ps1` packages `license-server` and `license-admin`; its tracked scopes do not include root `app` or `main.py`. |
| Current Admin Build | `no dependency` | Admin npm/Vite inputs are confined to `license-admin`; no import, copy, or build step references root `app`. |
| Current license-server | `no dependency` | Server packaging and runtime use `license-server/app` from the license-server working directory. They do not import the historical root `app`. |
| CI workflows | `no dependency` | `.github/workflows/license-ci.yml` scopes jobs to `license-server`, `license-admin`, and `deploy`; root `app` is not a CI input. |
| Cloud root pytest | `test dependency` | Root `tests` import the historical client `app`; B1-01 intentionally runs this domain from the Cloud root to avoid colliding with `license-server/app`. |
| README and root `main.py` | `documentation-only` and `runtime dependency` | README still documents `python main.py`; `main.py` imports the historical root `app`. This is a manual historical runtime path, not the current unified release path. |
| `build.bat` and `build_installer.bat` | `build dependency` | The batch files compile/package root `main.py` and `app`, then build the historical installer output. |
| `DDREC.spec` and `scripts/build_production_client.ps1` | `build dependency` | Both directly package root `main.py`, `app/assets`, and client modules. They remain an executable manual historical build flow. |

## Decision

The formal DDREC release, Cloud API build, Admin build, license-server runtime, and CI do not depend on
`cloud-license/app`. However, root tests plus explicit manual runtime/build entrypoints still do. The
copy therefore remains frozen in Batch 1: no feature synchronization, structural refactor, or wholesale
deletion. Decommissioning requires a separately approved change that first removes or redirects the
README, root `main.py`, BAT files, spec, installer inputs, production-client script, and root tests.

## B1-06 helper evidence inside the frozen copy

`_safe_exception_text`, `_upload_part_legacy`, and `_baidu_error_message` are definition-only private
helpers in the frozen copy. They are classified `DEFINITE_DEAD` by repository evidence but retained in
Batch 1 because the historical manual build surface has not yet been decommissioned. Public candidates
(`VideoIndexCache`, `VideoEntry`, `scan_video_files`, `FlowLayout`, `find_unfinished_recordings`) remain
`LIKELY_DEAD`; `camera.open_camera` remains `KEEP` as an explicit compatibility wrapper.
