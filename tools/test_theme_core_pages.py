from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidget

from app.core.config_manager import ConfigManager
from app.theme.theme_manager import ThemeManager
from app.ui.dialog_utils import DialogSizeManager
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication([])
    logger = logging.getLogger("theme-core-pages-test")
    with tempfile.TemporaryDirectory() as temporary_dir:
        config_manager = ConfigManager(Path(temporary_dir))
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
            window.window_max_button.click()
            app.processEvents()
            assert window.isMaximized()
            window.window_max_button.click()
            app.processEvents()
            assert not window.isMaximized()
            window.window_min_button.click()
            app.processEvents()
            assert window.isMinimized()
            window.showNormal()
            app.processEvents()
            capture_dir = os.environ.get("PM_THEME_CAPTURE_DIR", "").strip()
            if capture_dir:
                output_dir = Path(capture_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
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
                window.grab().save(str(Path(capture_dir) / "query-light.png"))
            theme_manager.preview_theme("dark")
            app.processEvents()
            if capture_dir:
                window.grab().save(str(Path(capture_dir) / "query-dark.png"))
            theme_manager.preview_theme("light")
            window.tabs.setCurrentIndex(0)
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
