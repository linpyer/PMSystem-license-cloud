from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DDREC_TEST_MODE"] = "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager
from app.core.database import DatabaseManager
from app.theme.theme_manager import ThemeManager
from app.ui.confirm_dialog import ConfirmActionDialog
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
        test_database = root / "data" / "theme_auxiliary.db"
        config_manager = ConfigManager(root / "config", database_path_override=test_database)
        config_manager.load()
        database = DatabaseManager(test_database, logger)
        theme_manager = ThemeManager(app, config_manager)
        app.setProperty("theme_manager", theme_manager)
        theme_manager.preview_theme("light")

        with patch.object(DialogSizeManager, "apply"), patch.object(DialogSizeManager, "remember"):
            safe_default = ConfirmActionDialog(
                title="删除视频",
                heading="确定删除这条视频记录吗？",
                description="删除后无法恢复。",
                info_label="单号",
                info_value="THEME-0001",
                sections=(("将删除：", ("本地视频记录", "本地视频文件")),),
                confirm_text="删除本地视频",
                destructive=True,
            )
            safe_default.show()
            app.processEvents()
            assert safe_default.header.objectName() == "confirmDialogHeader"
            assert safe_default.title_label.objectName() == "confirmDialogTitle"
            bounded = safe_default._bounded_drag_position(safe_default.pos())
            assert isinstance(bounded.x(), int) and isinstance(bounded.y(), int)
            assert safe_default.cancel_button.hasFocus()
            assert not safe_default.confirm_button.isDefault()
            QTest.keyClick(safe_default, Qt.Key_Return)
            app.processEvents()
            assert not safe_default.isVisible()

            failed_action = ConfirmActionDialog(
                title="删除视频",
                heading="确定删除吗？",
                confirm_text="删除本地视频",
                destructive=True,
            )
            failed_action._action = lambda: (False, "文件正在被占用")
            failed_action.show()
            app.processEvents()
            failed_action.confirm_button.click()
            QTest.qWait(10)
            assert failed_action.isVisible()
            assert failed_action.confirm_button.isEnabled()
            assert failed_action._toast_manager.container.isVisible()
            failed_action.reject()

            stats_notices: list[tuple[str, str]] = []
            dialogs = [
                ImportantMarkDialog("THEME-0001"),
                RecordDetailDialog(_record(), [], database=database, config=config_manager.config, logger=logger),
                DuplicateRecordsDialog(database, "THEME-0001", root, 1, lambda *_args: None, lambda: None, logger),
                NetdiskHistoryDialog(database, logger),
                StatsDetailDialog(database, "ship_orders", "发货单数", None, None),
                PackagingStatsDialog(database, notice_callback=lambda message, level: stats_notices.append((message, level))),
                HelpDialog(),
            ]
            started = time.perf_counter()
            for dialog in dialogs:
                dialog.show()
            app.processEvents()
            opened_ms = (time.perf_counter() - started) * 1000
            assert all(dialog.isVisible() for dialog in dialogs)
            dialogs[5]._load_single_stats()
            dialogs[5]._load_compare_stats()
            assert not stats_notices
            help_dialog = dialogs[6]
            assert help_dialog.help_tab_bar.currentIndex() == 0
            assert not help_dialog.previous_button.isEnabled()
            assert help_dialog.next_button.isEnabled()
            help_dialog.next_button.click()
            app.processEvents()
            assert help_dialog.help_tab_bar.currentIndex() == 1
            assert help_dialog.tabs.currentIndex() == 1
            assert help_dialog.previous_button.isEnabled()
            help_dialog.help_tab_bar.setCurrentIndex(0)
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
