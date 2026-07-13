from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager
from app.core.database import DatabaseManager
from app.theme.theme_manager import ThemeManager
from app.ui.dialog_utils import DialogSizeManager
from app.ui.help_dialog import HelpDialog
from app.ui.query_tab import (
    DuplicateRecordsDialog,
    ImportantMarkDialog,
    NetdiskHistoryDialog,
    RecordDetailDialog,
)
from app.ui.stats_dialog import PackagingStatsDialog, StatsDetailDialog


def _record() -> dict[str, object]:
    return {
        "id": 1,
        "order_no": "THEME-0001",
        "recorded_at": "2026-07-13 10:00:00",
        "file_path": "C:/theme-test/video.mp4",
        "file_size_text": "1.20 MB",
        "duration_text": "00:00:12",
        "status": "正常",
        "upload_status": "未上传",
        "record_type": "发货",
        "remark": "主题回归测试备注",
        "is_important": 1,
        "important_reason_type": "after_sale_dispute",
        "important_reason_custom": "",
        "important_note": "售后争议",
    }


def main() -> int:
    app = QApplication.instance() or QApplication([])
    logger = logging.getLogger("theme-auxiliary-dialogs-test")
    with tempfile.TemporaryDirectory() as temporary_dir:
        root = Path(temporary_dir)
        config_manager = ConfigManager(root / "config")
        config_manager.load()
        database = DatabaseManager(root / "data" / "theme_test.db", logger)
        theme_manager = ThemeManager(app, config_manager)
        app.setProperty("theme_manager", theme_manager)
        theme_manager.preview_theme("light")

        with patch.object(DialogSizeManager, "apply"), patch.object(DialogSizeManager, "remember"):
            dialogs = [
                ImportantMarkDialog("THEME-0001"),
                RecordDetailDialog(_record(), [], database=database, config=config_manager.config, logger=logger),
                DuplicateRecordsDialog(database, "THEME-0001", root, 1, lambda *_args: None, lambda: None, logger),
                NetdiskHistoryDialog(database, logger),
                StatsDetailDialog(database, "ship_orders", "发货单数", None, None),
                PackagingStatsDialog(database),
                HelpDialog(),
            ]
            started = time.perf_counter()
            for dialog in dialogs:
                dialog.show()
            app.processEvents()
            opened_ms = (time.perf_counter() - started) * 1000
            assert all(dialog.isVisible() for dialog in dialogs)
            capture_dir = os.environ.get("PM_THEME_CAPTURE_DIR", "").strip()
            if capture_dir:
                output_dir = Path(capture_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                dialogs[1].grab().save(str(output_dir / "record-detail-light.png"))
                dialogs[5].grab().save(str(output_dir / "statistics-light.png"))
                dialogs[6].grab().save(str(output_dir / "help-light.png"))

            started = time.perf_counter()
            theme_manager.preview_theme("dark")
            app.processEvents()
            switch_ms = (time.perf_counter() - started) * 1000
            assert theme_manager.resolved_theme() == "dark"
            assert "#212121" in app.styleSheet()
            assert dialogs[1].objectName() == "recordDetailDialog"
            assert dialogs[4].objectName() == "statsDetailDialog"
            assert dialogs[5].single_chart._theme_tokens.window_background == "#212121"
            if capture_dir:
                output_dir = Path(capture_dir)
                dialogs[1].grab().save(str(output_dir / "record-detail-dark.png"))
                dialogs[5].grab().save(str(output_dir / "statistics-dark.png"))
                dialogs[6].grab().save(str(output_dir / "help-dark.png"))

            theme_manager.preview_theme("light")
            app.processEvents()
            for dialog in dialogs:
                dialog.close()
            theme_manager.cancel_preview()
            connection = getattr(database, "_connection", None)
            if connection is not None:
                connection.close()
                database._connection = None

    print(f"theme auxiliary dialog tests passed; open={opened_ms:.1f}ms switch={switch_ms:.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
