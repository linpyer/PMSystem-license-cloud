from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database_paths import (  # noqa: E402
    APP_VENDOR_DIR_NAME,
    get_canonical_database_path,
    local_app_data_dir,
    retired_database_root,
)
from app.core.version import APP_DATA_DIR_NAME, APP_NAME  # noqa: E402


@dataclass(frozen=True)
class LegacyDatabaseLocation:
    label: str
    path: Path


@dataclass(frozen=True)
class RetirementFile:
    label: str
    source: Path
    destination_name: str
    size: int
    sha256: str


def known_legacy_database_locations() -> list[LegacyDatabaseLocation]:
    """Return only database paths explicitly used by previous PMSystem code."""
    local_root = local_app_data_dir()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    locations = [
        LegacyDatabaseLocation("development", PROJECT_ROOT / "pm_system.db"),
        LegacyDatabaseLocation("legacy_user", local_root / APP_DATA_DIR_NAME / "pm_system.db"),
        LegacyDatabaseLocation(
            "prior_vendor_root",
            local_root / APP_VENDOR_DIR_NAME / APP_DATA_DIR_NAME / "pm_system.db",
        ),
        LegacyDatabaseLocation(
            "prior_vendor_database",
            local_root / APP_VENDOR_DIR_NAME / APP_DATA_DIR_NAME / "data" / "pmsystem.db",
        ),
        LegacyDatabaseLocation("installed", program_files / APP_DATA_DIR_NAME / "pm_system.db"),
        LegacyDatabaseLocation("installed_x86", program_files_x86 / APP_DATA_DIR_NAME / "pm_system.db"),
    ]
    canonical = _path_key(get_canonical_database_path())
    result: list[LegacyDatabaseLocation] = []
    seen: set[str] = set()
    for location in locations:
        key = _path_key(location.path)
        if key == canonical or key in seen:
            continue
        seen.add(key)
        result.append(LegacyDatabaseLocation(location.label, location.path.expanduser().resolve()))
    return result


def collect_retirement_files(
    locations: Iterable[LegacyDatabaseLocation],
) -> list[RetirementFile]:
    canonical = _path_key(get_canonical_database_path())
    retired_root = retired_database_root().resolve()
    files: list[RetirementFile] = []
    seen: set[str] = set()
    for location in locations:
        for suffix in ("", "-wal", "-shm"):
            source = location.path if not suffix else location.path.with_name(location.path.name + suffix)
            source = source.expanduser().resolve()
            key = _path_key(source)
            if key in seen or not source.is_file():
                continue
            if key == canonical or _is_relative_to(source, retired_root):
                raise RuntimeError(f"拒绝隔离正式数据库或隔离目录文件：{source}")
            seen.add(key)
            files.append(
                RetirementFile(
                    label=location.label,
                    source=source,
                    destination_name=f"{location.label}_{source.name}.abandoned",
                    size=source.stat().st_size,
                    sha256=_sha256(source),
                )
            )
    return files


def retire_legacy_databases(
    locations: Iterable[LegacyDatabaseLocation],
    *,
    execute: bool,
    destination_root: Path | None = None,
    check_running_processes: bool = True,
    timestamp: datetime | None = None,
) -> tuple[Path | None, list[dict[str, object]]]:
    files = collect_retirement_files(locations)
    if not execute:
        return None, [_manifest_entry(item, None, None) for item in files]
    if not files:
        return None, []
    if check_running_processes:
        _ensure_pmsystem_not_running()
    _ensure_files_not_locked([item.source for item in files])

    retired_at = timestamp or datetime.now()
    root = (destination_root or retired_database_root()).expanduser().resolve()
    destination = _unique_destination(root, retired_at.strftime("%Y%m%d_%H%M%S"))
    destination.mkdir(parents=True, exist_ok=False)
    moved: list[tuple[Path, Path]] = []
    entries: list[dict[str, object]] = []
    try:
        for item in files:
            target = destination / item.destination_name
            shutil.move(str(item.source), str(target))
            moved.append((item.source, target))
            entries.append(_manifest_entry(item, target, retired_at))
        manifest = destination / "retired_manifest.json"
        manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                shutil.move(str(target), str(source))
        if destination.exists() and not any(destination.iterdir()):
            destination.rmdir()
        raise
    return destination, entries


def _manifest_entry(
    item: RetirementFile,
    destination: Path | None,
    retired_at: datetime | None,
) -> dict[str, object]:
    return {
        "original_path": str(item.source),
        "retired_path": str(destination) if destination is not None else "",
        "size": item.size,
        "sha256": item.sha256,
        "retired_at": retired_at.isoformat(timespec="seconds") if retired_at is not None else "",
    }


def _ensure_pmsystem_not_running() -> None:
    if os.name != "nt":
        return
    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("无法确认 PMSystem 是否正在运行，已停止隔离操作")
    raw = result.stdout.strip()
    processes = json.loads(raw) if raw else []
    if isinstance(processes, dict):
        processes = [processes]
    blockers: list[str] = []
    project_key = os.path.normcase(str(PROJECT_ROOT))
    for process in processes:
        pid = int(process.get("ProcessId") or 0)
        if pid == os.getpid():
            continue
        name = str(process.get("Name") or "")
        command_line = str(process.get("CommandLine") or "")
        name_lower = name.lower()
        command_key = os.path.normcase(command_line)
        is_app = "pmsystem" in name_lower or APP_NAME in name
        is_development = (
            name_lower.startswith("python")
            and project_key in command_key
            and ("main.py" in command_key or "-m app" in command_key)
        )
        if is_app or is_development:
            blockers.append(f"pid={pid}, name={name}")
    if blockers:
        raise RuntimeError("检测到 PMSystem 或开发版 Python 正在运行：" + "; ".join(blockers))


def _ensure_files_not_locked(paths: Iterable[Path]) -> None:
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    invalid_handle = ctypes.c_void_p(-1).value
    for path in paths:
        handle = kernel32.CreateFileW(
            str(path),
            0x80000000,
            0,
            None,
            3,
            0x80,
            None,
        )
        if handle == invalid_handle:
            raise RuntimeError(f"旧数据库正在使用或无法独占访问：{path}")
        kernel32.CloseHandle(handle)


def _unique_destination(root: Path, timestamp_name: str) -> Path:
    candidate = root / timestamp_name
    counter = 1
    while candidate.exists():
        candidate = root / f"{timestamp_name}_{counter:02d}"
        counter += 1
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.expanduser().resolve())))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="隔离 PMSystem 已弃用的旧数据库文件")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="仅列出将隔离的文件")
    mode.add_argument("--execute", action="store_true", help="执行文件级隔离，不删除数据")
    args = parser.parse_args()

    locations = known_legacy_database_locations()
    destination, entries = retire_legacy_databases(locations, execute=args.execute)
    if not entries:
        print("未发现代码已知路径中的旧数据库文件。")
        return 0
    if args.dry_run:
        print(f"正式数据库（不会操作）：{get_canonical_database_path()}")
        print(f"计划隔离目录：{retired_database_root()}\\YYYYMMDD_HHMMSS")
        for entry in entries:
            source = Path(str(entry["original_path"]))
            print(
                f"[DRY-RUN] {source} | size={entry['size']} | "
                f"sha256={entry['sha256']} | wal_shm={'yes' if source.name.endswith(('-wal', '-shm')) else 'no'}"
            )
        return 0

    print(f"旧数据库已隔离到：{destination}")
    for entry in entries:
        print(f"[RETIRED] {entry['original_path']} -> {entry['retired_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
