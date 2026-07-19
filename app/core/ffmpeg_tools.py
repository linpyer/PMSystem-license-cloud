from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess

from app.utils.runtime_paths import app_dir, resource_path


class FFmpegUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegToolchain:
    ffmpeg: Path
    ffprobe: Path
    has_libx264: bool
    version_line: str


def _tool_candidates(name: str) -> list[Path]:
    relative = Path("tools") / "ffmpeg" / name
    candidates = [
        resource_path(relative),
        app_dir() / relative,
        Path(__file__).resolve().parents[2] / relative,
    ]
    from_path = shutil.which(name)
    if from_path:
        candidates.append(Path(from_path))
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def resolve_ffmpeg_tool(name: str, *, required: bool = True) -> Path | None:
    for candidate in _tool_candidates(name):
        if candidate.is_file():
            return candidate
    if required:
        raise FFmpegUnavailableError(f"{name} 不存在或不可访问")
    return None


def _run_tool(path: Path, *args: str, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    startupinfo = None
    creationflags = 0
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FFmpegUnavailableError(f"{path.name} 无法启动") from exc


@lru_cache(maxsize=1)
def inspect_ffmpeg_toolchain() -> FFmpegToolchain:
    ffmpeg = resolve_ffmpeg_tool("ffmpeg.exe")
    ffprobe = resolve_ffmpeg_tool("ffprobe.exe")
    assert ffmpeg is not None and ffprobe is not None

    version = _run_tool(ffmpeg, "-hide_banner", "-version")
    if version.returncode != 0:
        raise FFmpegUnavailableError("ffmpeg.exe 启动检查失败")
    encoders = _run_tool(ffmpeg, "-hide_banner", "-encoders")
    if encoders.returncode != 0:
        raise FFmpegUnavailableError("无法读取 FFmpeg 编码器列表")
    has_libx264 = "libx264" in f"{encoders.stdout}\n{encoders.stderr}"
    if not has_libx264:
        raise FFmpegUnavailableError("随软件提供的 FFmpeg 不包含 H.264 编码能力")
    probe = _run_tool(ffprobe, "-hide_banner", "-version")
    if probe.returncode != 0:
        raise FFmpegUnavailableError("ffprobe.exe 启动检查失败")
    version_line = next((line.strip() for line in version.stdout.splitlines() if line.strip()), "ffmpeg")
    return FFmpegToolchain(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        has_libx264=True,
        version_line=version_line,
    )
