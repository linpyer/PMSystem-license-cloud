from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVER = ROOT / "scripts" / "create_reproducible_tar.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_archiver(source: Path, output: Path, mtime: int = 1_700_000_000) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ARCHIVER),
            "--source",
            str(source),
            "--output",
            str(output),
            "--root-name",
            "release-fixture",
            "--mtime",
            str(mtime),
        ],
        check=True,
    )


def test_repeated_archives_have_identical_sha_and_normalized_metadata(tmp_path: Path) -> None:
    source = tmp_path / "payload"
    nested = source / "scripts"
    nested.mkdir(parents=True)
    (source / "z.txt").write_text("same payload\n", encoding="utf-8")
    (nested / "run.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    fixed_mtime = 1_700_000_000
    run_archiver(source, first, fixed_mtime)
    os.utime(source / "z.txt", (1_800_000_000, 1_800_000_000))
    os.utime(nested / "run.sh", (1_900_000_000, 1_900_000_000))
    run_archiver(source, second, fixed_mtime)

    assert sha256(first) == sha256(second)
    assert int.from_bytes(first.read_bytes()[4:8], "little") == fixed_mtime
    with tarfile.open(first, "r:gz") as archive:
        members = archive.getmembers()
    assert [member.name for member in members] == [
        "release-fixture",
        "release-fixture/scripts",
        "release-fixture/scripts/run.sh",
        "release-fixture/z.txt",
    ]
    assert all(member.mtime == fixed_mtime for member in members)
    assert all((member.uid, member.gid, member.uname, member.gname) == (0, 0, "root", "root") for member in members)
    assert members[0].mode == 0o755
    assert members[2].mode == 0o755
    assert members[3].mode == 0o644


def test_gzip_header_has_no_original_filename(tmp_path: Path) -> None:
    source = tmp_path / "payload"
    source.mkdir()
    (source / "file.txt").write_text("payload", encoding="utf-8")
    archive = tmp_path / "named-output.tar.gz"
    run_archiver(source, archive)
    header = archive.read_bytes()
    assert header[:3] == b"\x1f\x8b\x08"
    assert header[3] & 0x08 == 0
    with gzip.open(archive, "rb") as stream:
        assert stream.read()
