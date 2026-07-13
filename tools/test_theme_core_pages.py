from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PMSYSTEM_TEST_MODE"] = "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidget

from app.core.config_manager import ConfigManager
from app.theme.theme_manager import ThemeManager
from app.ui.dialog_utils import DialogSizeManager
from app.ui.main_window import MainWindow
from app.ui.monitor_tab import is_camera_status_message


def main() -> int:
    app = QApplication.instance() or QApplication([])
    logger = logging.getLogger("theme-core-pages-test")
    with tempfile.TemporaryDirectory() as temporary_dir:
        test_root = Path(temporary_dir)
        config_manager = ConfigManager(
            test_root,
            database_path_override=test_root / "data" / "theme_core_pages.db",
        )
        config_manager.load()
        theme_manager = ThemeManager(app, config_manager)
        app.setProperty("theme_manager", theme_manager)
        theme_manager.apply_configured_theme()

        with patch.object(DialogSizeManager, "apply"), patch.object(DialogSizeManager, "remember"):
            window = MainWindow(config_manager=config_manager, logger=logger, theme_manager=theme_manager)
            assert not window.stats_button.icon().isNull()
            assert not window.settings_button.icon().isNull()
            assert not window.help_button.icon().isNull()
            assert not window.window_min_button.icon().isNull()
            assert not window.window_max_button.icon().isNull()
            assert not window.window_close_button.icon().isNull()
            assert len(window.findChildren(QTableWidget)) >= 1
            window.show()
            app.processEvents()
            assert window.isVisible()
            for line_edit in (window.monitor_tab.scan_input, window.query_tab.search_input):
                clear_button = line_edit.clear_button()
                assert clear_button is not None
                assert clear_button.objectName() == "clearInputButton"
                assert clear_button.minimumSize().width() == 30
                assert clear_button.minimumSize().height() == 30
                assert clear_button.maximumSize().width() == 30
                assert clear_button.maximumSize().height() == 30
                assert clear_button.iconSize().width() == 18
                assert clear_button.iconSize().height() == 18
                assert not clear_button.icon().isNull()
                assert not clear_button.isVisible()
                line_edit.setText("123456")
                app.processEvents()
                clear_button.click()
                app.processEvents()
                assert line_edit.text() == ""
                assert line_edit.hasFocus()
                assert not clear_button.isVisible()
            assert is_camera_status_message("摄像头连接异常，请检查 iVCam")
            assert is_camera_status_message("摄像头已恢复")
            assert is_camera_status_message("当前摄像头实际帧率低于配置帧率")
            assert not is_camera_status_message("录制中不能刷新摄像头")
            assert not is_camera_status_message("摄像头已刷新")
            assert not is_camera_status_message("摄像头刷新失败：摄像头不可用")
            window._toast_manager.clear()
            with patch.object(window.monitor_tab.voice_prompt, "play", return_value=True) as play_voice:
                window.monitor_tab._on_camera_status_changed(False, "摄像头连接异常")
                window.monitor_tab._on_camera_status_changed(False, "摄像头读取失败")
                assert play_voice.call_count == 1
                window.monitor_tab._on_camera_status_changed(True, "摄像头已恢复")
                window.monitor_tab._on_camera_status_changed(False, "摄像头连接异常")
                assert play_voice.call_count == 2
            app.processEvents()
            assert not window._toast_manager.container.isVisible()
            assert not window._toast_manager._queue
            with patch.object(window.monitor_tab.recorder, "restart_camera") as restart_camera:
                window.monitor_tab._refresh_camera()
                restart_camera.assert_called_once_with(report_result=True)
                assert not window.monitor_tab.refresh_camera_button.isEnabled()
                window.monitor_tab._on_manual_camera_refresh_finished(True, "")
                app.processEvents()
                assert window.monitor_tab.refresh_camera_button.isEnabled()
                assert window._toast_manager._active_message == "摄像头已刷新"
            window._toast_manager.clear()
            window._toast_manager.clear()
            tab_geometry = window.tabs.tabBar().geometry()
            actions_geometry = window.navigation_actions.geometry()
            window.show_status_tip("顶部导航悬浮提示不会挤动任何按钮，较长内容会在安全区域内自动省略" * 6)
            app.processEvents()
            toast_geometry = window._toast_manager.container.geometry()
            anchor_geometry = window.toast_titlebar_available_rect()
            assert window._toast_manager.container.isVisible()
            assert not window._toast_manager.label.wordWrap()
            assert anchor_geometry.contains(toast_geometry)
            assert abs(anchor_geometry.center().y() - toast_geometry.center().y()) <= 1
            assert window.tabs.tabBar().geometry() == tab_geometry
            assert window.navigation_actions.geometry() == actions_geometry
            assert window._toast_manager.label.text().endswith("…")
            window.window_max_button.click()
            app.processEvents()
            assert window.isMaximized()
            assert (
                not window._toast_manager.container.isVisible()
                or window.toast_titlebar_available_rect().contains(window._toast_manager.container.geometry())
            )
            window.window_max_button.click()
            app.processEvents()
            assert not window.isMaximized()
            assert window.toast_titlebar_available_rect().contains(window._toast_manager.container.geometry())
            window.window_min_button.click()
            app.processEvents()
            assert window.isMinimized()
            window.showNormal()
            app.processEvents()
            capture_dir = os.environ.get("PM_THEME_CAPTURE_DIR", "").strip()
            if capture_dir:
                output_dir = Path(capture_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                window.monitor_tab.scan_input.setText("79018528776862")
                app.processEvents()
                window.grab().save(str(output_dir / "theme-system.png"))

            theme_manager.preview_theme("dark")
            app.processEvents()
            assert theme_manager.resolved_theme() == "dark"
            assert "#212121" in app.styleSheet()
            if capture_dir:
                window.grab().save(str(Path(capture_dir) / "theme-dark.png"))

            theme_manager.preview_theme("light")
            app.processEvents()
            assert theme_manager.resolved_theme() == "light"
            assert "#F7F7F8" in app.styleSheet()
            if capture_dir:
                window.grab().save(str(Path(capture_dir) / "theme-light.png"))

            window.tabs.setCurrentIndex(1)
            QTest.qWait(600)
            app.processEvents()
            assert window.tabs.currentWidget() is window.query_tab
            if capture_dir:
                window.query_tab.search_input.setText("79018528776862")
                app.processEvents()
                window.grab().save(str(Path(capture_dir) / "query-light.png"))
            theme_manager.preview_theme("dark")
            app.processEvents()
            if capture_dir:
                window.grab().save(str(Path(capture_dir) / "query-dark.png"))
            theme_manager.preview_theme("light")
            window.tabs.setCurrentIndex(0)
            window.monitor_tab.scan_input.clear()
            window.query_tab.search_input.clear()
            app.processEvents()

            window._show_settings_dialog()
            assert window.settings_dialog is not None
            assert window.settings_dialog.tabs.count() == 5
            for index in range(window.settings_dialog.tabs.count()):
                window.settings_dialog.tabs.setCurrentIndex(index)
                app.processEvents()
                assert window.settings_dialog.tabs.currentIndex() == index
            window.settings_dialog.tabs.setCurrentIndex(0)
            app.processEvents()
            assert window.settings_dialog.isVisible()
            if capture_dir:
                window.settings_dialog.grab().save(str(Path(capture_dir) / "settings-light.png"))
            theme_manager.preview_theme("dark")
            app.processEvents()
            if capture_dir:
                window.settings_dialog.grab().save(str(Path(capture_dir) / "settings-dark.png"))
            window.settings_dialog.close()

            theme_manager.cancel_preview()
            window.close()

    print("theme core page tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
