from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PMSYSTEM_TEST_MODE"] = "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QToolButton

from app.core.config_manager import ConfigManager
from app.theme.theme_manager import ThemeManager
from app.ui.themed_line_edit import ThemedClearableLineEdit


def main() -> int:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary_dir:
        test_root = Path(temporary_dir)
        config_manager = ConfigManager(
            test_root,
            database_path_override=test_root / "data" / "themed_line_edit.db",
        )
        config_manager.load()
        theme_manager = ThemeManager(app, config_manager)
        app.setProperty("theme_manager", theme_manager)
        theme_manager.apply_configured_theme()

        editor = ThemedClearableLineEdit()
        editor.setObjectName("scanInput")
        editor.resize(420, 40)
        editor.show()
        app.processEvents()

        buttons = editor.findChildren(QToolButton)
        assert len(buttons) == 1
        clear_button = editor.clear_button()
        assert clear_button is buttons[0]
        assert clear_button.objectName() == "clearInputButton"
        assert clear_button.size().width() == 30
        assert clear_button.size().height() == 30
        assert clear_button.iconSize().width() == 18
        assert clear_button.iconSize().height() == 18
        assert abs(clear_button.geometry().center().y() - editor.rect().center().y()) <= 1
        assert not clear_button.isVisible()

        return_pressed = QSignalSpy(editor.returnPressed)
        editor.setText("79018528776862")
        app.processEvents()
        assert clear_button.isVisible()
        assert clear_button.geometry().right() < editor.rect().right()
        clear_button.click()
        app.processEvents()
        assert editor.text() == ""
        assert editor.hasFocus()
        assert return_pressed.count() == 0
        assert not clear_button.isVisible()

        for mode in ("light", "dark", "system"):
            theme_manager.preview_theme(mode)
            app.processEvents()
            assert not clear_button.icon().isNull()
            assert clear_button.size().width() == 30
            assert clear_button.size().height() == 30

        editor.close()
        theme_manager.cancel_preview()

    print(f"themed clear line edit test passed at scale {os.environ.get('QT_SCALE_FACTOR', '1.0')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
