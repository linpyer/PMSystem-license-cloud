from __future__ import annotations

import os
import sys
import tempfile
import logging
import time
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DDREC_TEST_MODE"] = "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.core.config_manager import ConfigManager, normalize_appearance_config
from app.core.voice_prompt import VoicePrompt
from app.theme.theme_manager import ThemeManager
from app.ui.dialog_utils import DialogSizeManager
from app.ui.settings_dialog import SettingsDialog
from app.ui.toast import ToastManager, show_toast


def _wait_until(predicate, timeout_ms: int = 1200, step_ms: int = 20) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(step_ms)
    return bool(predicate())


def main() -> int:
    assert normalize_appearance_config(None) == {"theme": "system"}
    assert normalize_appearance_config({"theme": "DARK"}) == {"theme": "dark"}
    assert normalize_appearance_config({"theme": "invalid"}) == {"theme": "system"}

    with tempfile.TemporaryDirectory() as temporary_dir:
        test_root = Path(temporary_dir)
        test_database = test_root / "data" / "theme_manager.db"
        manager = ConfigManager(test_root, database_path_override=test_database)
        config = manager.load()
        assert config["appearance"]["theme"] == "system"
        assert "appearance" in manager._exportable_settings()

        app = QApplication.instance() or QApplication([])
        theme_manager = ThemeManager(app, manager)
        theme_manager.apply_configured_theme()
        assert theme_manager.current_mode() == "system"
        assert theme_manager.resolved_theme() in {"light", "dark"}

        # Hold timing starts only after fade-in, and queued messages never
        # interrupt the active animation.
        toast_owner = QDialog()
        toast_owner.resize(640, 420)
        toast_owner.show()
        toast_manager = ToastManager(toast_owner, logging.getLogger("toast-test"))
        toast_manager.show("first", "info", 2400)
        assert toast_manager._state == "fading_in"
        assert not toast_manager.timer.isActive()
        toast_manager.show("first", "info", 2400)
        assert not toast_manager._queue
        toast_manager.show("second", "success", 2400)
        assert [item[0] for item in toast_manager._queue] == ["second"]
        assert _wait_until(lambda: toast_manager._state == "visible")
        assert toast_manager.timer.isActive()
        assert toast_manager.container.isVisibleTo(toast_owner)
        assert toast_manager.label.graphicsEffect() is None
        assert toast_manager.container.graphicsEffect() is toast_manager._opacity_effect
        QTest.qWait(500)
        assert toast_manager._state == "visible"
        assert toast_manager.container.isVisibleTo(toast_owner)
        for index in range(10):
            toast_manager.show(f"queued-{index}", "info", 2400)
        assert len(toast_manager._queue) == toast_manager._max_queue_length
        toast_manager.clear()
        assert toast_manager._state == "idle"
        assert not toast_manager.timer.isActive()
        assert not toast_manager._queue
        assert toast_manager.label.text() == ""
        toast_manager.show("default-duration")
        assert toast_manager._active_duration_ms == 2400
        assert toast_manager.container.width() >= 220
        started_at = time.monotonic()
        assert _wait_until(lambda: toast_manager._state == "visible")
        remaining_before_resize = toast_manager.timer.remainingTime()
        toast_owner.resize(700, 460)
        app.processEvents()
        assert toast_manager._state == "visible"
        assert 0 < toast_manager.timer.remainingTime() <= remaining_before_resize
        QTest.qWait(2250)
        assert toast_manager._state == "visible"
        assert toast_manager.container.isVisibleTo(toast_owner)
        QTest.qWait(450)
        assert toast_manager._state == "idle"
        assert time.monotonic() - started_at >= 2.65
        toast_manager.clear()
        toast_owner.close()

        theme_manager.preview_theme("dark")
        assert theme_manager.current_mode() == "dark"
        theme_manager.cancel_preview()
        assert theme_manager.current_mode() == "system"

        theme_manager.preview_theme("light")
        theme_manager.commit_theme("light")
        manager.update({"appearance": {"theme": theme_manager.current_mode()}})
        assert manager.config["appearance"]["theme"] == "light"

        reloaded = ConfigManager(test_root, database_path_override=test_database)
        reloaded.load()
        assert reloaded.config["appearance"]["theme"] == "light"

        export_path = Path(temporary_dir) / "theme_config.zip"
        reloaded.export_config(export_path)
        reloaded.update({"appearance": {"theme": "dark"}})
        reloaded.import_config(export_path)
        assert reloaded.config["appearance"]["theme"] == "light"

        # Verify the SettingsDialog preview session rolls back a non-saved choice.
        manager.update({"appearance": {"theme": "system"}})
        theme_manager.apply_configured_theme()
        with patch.object(DialogSizeManager, "apply"), patch.object(DialogSizeManager, "remember"):
            dialog = SettingsDialog(
                config_manager=manager,
                logger=logging.getLogger("theme-test"),
                voice_prompt=VoicePrompt(manager.config, logging.getLogger("theme-test")),
                is_recording_callback=lambda: False,
                is_syncing_callback=lambda: False,
                theme_manager=theme_manager,
            )
            dialog.show()
            app.processEvents()
            assert not hasattr(dialog, "_toast_manager")
            dialog.theme_mode_buttons["dark"].click()
            assert dialog.theme_mode_buttons["dark"].isChecked()
            assert theme_manager.current_mode() == "system"
            app.processEvents()
            assert theme_manager.current_mode() == "dark"
            assert not dialog.netdisk_auth_button.icon().isNull()
            assert not dialog.netdisk_test_button.icon().isNull()
            show_toast(dialog, "基础配置已保存并应用")
            app.processEvents()
            assert dialog._toast_manager.container.isVisible()
            assert dialog._toast_manager._titlebar_anchor_rect() is None
            assert dialog._toast_manager.label.wordWrap()
            dialog.reject()
            app.processEvents()
            assert theme_manager.current_mode() == "system"
            assert not dialog._toast_manager.container.isVisible()
            assert dialog._toast_manager.label.text() == ""

            reopened_dialog = SettingsDialog(
                config_manager=manager,
                logger=logging.getLogger("theme-test"),
                voice_prompt=VoicePrompt(manager.config, logging.getLogger("theme-test")),
                is_recording_callback=lambda: False,
                is_syncing_callback=lambda: False,
                theme_manager=theme_manager,
            )
            assert reopened_dialog.theme_mode_buttons["system"].isChecked()
            assert not hasattr(reopened_dialog, "_toast_manager")
            reopened_dialog.reject()
            app.processEvents()

    print("theme manager tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
