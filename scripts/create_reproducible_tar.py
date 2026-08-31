"""Create a deterministic tar.gz archive for an immutable Cloud release."""

from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import stat
import tarfile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root-name", required=True)
    parser.add_argument("--mtime", required=True, type=int)
    return parser.parse_args()


def normalized_info(name: str, *, is_directory: bool, size: int, mtime: int, executable: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE if is_directory else tarfile.REGTYPE
    info.size = 0 if is_directory else size
    info.mode = 0o755 if is_directory or executable else 0o644
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = mtime
    return info


def create_archive(source: Path, output: Path, root_name: str, mtime: int) -> None:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    if not root_name or "/" in root_name or "\\" in root_name or root_name in {".", ".."}:
        raise ValueError("root-name must be one safe path segment")
    if mtime < 0:
        raise ValueError("mtime must be non-negative")

    entries = sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix())
    for entry in entries:
        if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
            raise ValueError(f"unsupported archive entry: {entry}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=mtime) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    archive.addfile(normalized_info(f"{root_name}/", is_directory=True, size=0, mtime=mtime))
                    for entry in entries:
                        relative = entry.relative_to(source).as_posix()
                        archive_name = f"{root_name}/{relative}"
                        if entry.is_dir():
                            archive.addfile(normalized_info(f"{archive_name}/", is_directory=True, size=0, mtime=mtime))
                            continue
                        file_stat = entry.stat()
                        executable = entry.suffix.lower() == ".sh" or bool(file_stat.st_mode & stat.S_IXUSR)
                        info = normalized_info(
                            archive_name,
                            is_directory=False,
                            size=file_stat.st_size,
                            mtime=mtime,
                            executable=executable,
                        )
                        with entry.open("rb") as payload:
                            archive.addfile(info, payload)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    create_archive(args.source, args.output, args.root_name, args.mtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
