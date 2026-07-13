from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config_manager import ConfigManager
from app.core.database import DatabaseManager
from app.core.database_paths import (
    DATABASE_TEST_MODE_ENV,
    get_canonical_database_path,
)
from scripts.retire_legacy_databases import (
    LegacyDatabaseLocation,
    retire_legacy_databases,
)


def _create_old_database(path: Path, order_no: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE videos (id INTEGER PRIMARY KEY, order_no TEXT, file_name TEXT, file_path TEXT)"
        )
        connection.execute(
            "INSERT INTO videos (order_no, file_name, file_path) VALUES (?, ?, ?)",
            (order_no, f"{order_no}.mp4", str(path.with_suffix(".mp4"))),
        )
        connection.commit()


def _create_upgrade_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                record_type TEXT,
                status TEXT,
                recorded_at TEXT,
                updated_at TEXT
            )
            """
        )
        connection.commit()


def main() -> int:
    original_local_app_data = os.environ.get("LOCALAPPDATA")
    original_test_mode = os.environ.get(DATABASE_TEST_MODE_ENV)
    try:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            fake_local_app_data = root / "local_app_data"
            os.environ["LOCALAPPDATA"] = str(fake_local_app_data)
            os.environ.pop(DATABASE_TEST_MODE_ENV, None)

            canonical = get_canonical_database_path()
            expected = fake_local_app_data / "PMSystem" / "data" / "pmsystem.db"
            assert canonical == expected

            old_databases = (
                root / "project" / "pm_system.db",
                root / "installation" / "pm_system.db",
                fake_local_app_data / "PMSystem" / "pm_system.db",
            )
            for index, old_database in enumerate(old_databases, 1):
                _create_old_database(old_database, f"OLD-{index}")

            manager = DatabaseManager(canonical)
            assert canonical.exists()
            assert manager.count_videos() == 0
            tables = {
                str(row[0])
                for row in manager.get_connection().execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "videos" in tables
            assert "database_migrations" not in tables
            manager.close()

            existing = DatabaseManager(canonical)
            assert existing.count_videos() == 0
            existing.close()
            assert all(path.exists() for path in old_databases)

            config_manager = ConfigManager(root / "config")
            assert config_manager.database_path == canonical
            original_cwd = Path.cwd()
            try:
                os.chdir(root / "project")
                assert get_canonical_database_path() == canonical
            finally:
                os.chdir(original_cwd)

            os.environ[DATABASE_TEST_MODE_ENV] = "1"
            injected = root / "fixtures" / "database" / "test.db"
            test_config = ConfigManager(root / "test_config", database_path_override=injected)
            assert test_config.database_path == injected.resolve()
            test_manager = DatabaseManager(injected)
            assert test_manager.count_videos() == 0
            test_manager.close()

            try:
                ConfigManager(root / "bad_test_config")
            except RuntimeError:
                pass
            else:
                raise AssertionError("test mode accepted ConfigManager without an injected database")
            for forbidden in (canonical, PROJECT_ROOT / "pm_system.db"):
                try:
                    DatabaseManager(forbidden)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError(f"test mode accepted forbidden database path: {forbidden}")

            upgrade_path = root / "fixtures" / "database" / "upgrade.db"
            _create_upgrade_fixture(upgrade_path)
            upgraded = DatabaseManager(upgrade_path)
            upgraded_columns = {
                str(row["name"])
                for row in upgraded.get_connection().execute("PRAGMA table_info(videos)").fetchall()
            }
            assert {"normalized_file_path", "upload_status", "file_hash"}.issubset(upgraded_columns)
            upgraded.close()

            retirement_source = root / "fixtures" / "legacy" / "pm_system.db"
            retirement_source.parent.mkdir(parents=True, exist_ok=True)
            retirement_source.write_bytes(b"legacy-main")
            retirement_wal = retirement_source.with_name(retirement_source.name + "-wal")
            retirement_shm = retirement_source.with_name(retirement_source.name + "-shm")
            retirement_wal.write_bytes(b"legacy-wal")
            retirement_shm.write_bytes(b"legacy-shm")
            location = LegacyDatabaseLocation("fixture", retirement_source)
            retired_root = root / "retired_output"

            dry_destination, dry_entries = retire_legacy_databases(
                [location],
                execute=False,
                destination_root=retired_root,
            )
            assert dry_destination is None
            assert len(dry_entries) == 3
            assert retirement_source.exists() and retirement_wal.exists() and retirement_shm.exists()
            assert not retired_root.exists()

            destination, retired_entries = retire_legacy_databases(
                [location],
                execute=True,
                destination_root=retired_root,
                check_running_processes=False,
                timestamp=datetime(2026, 7, 14, 12, 0, 0),
            )
            assert destination == retired_root / "20260714_120000"
            assert len(retired_entries) == 3
            assert not retirement_source.exists()
            assert not retirement_wal.exists()
            assert not retirement_shm.exists()
            manifest_path = destination / "retired_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert len(manifest) == 3
            assert all(Path(str(item["retired_path"])).suffix == ".abandoned" for item in manifest)
            assert all(len(str(item["sha256"])) == 64 for item in manifest)
            assert canonical.exists()

            gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
            assert all(pattern in gitignore for pattern in ("*.db", "*-wal", "*-shm"))
            packaged_sources = (
                (PROJECT_ROOT / "PMSystem.spec").read_text(encoding="utf-8")
                + (PROJECT_ROOT / "installer" / "PMSystem.iss").read_text(encoding="utf-8")
            ).lower()
            assert "pmsystem.db" not in packaged_sources
            assert "pm_system.db" not in packaged_sources
            assert "retired_legacy_databases" not in packaged_sources
    finally:
        if original_local_app_data is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = original_local_app_data
        if original_test_mode is None:
            os.environ.pop(DATABASE_TEST_MODE_ENV, None)
        else:
            os.environ[DATABASE_TEST_MODE_ENV] = original_test_mode

    print("database policy tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
