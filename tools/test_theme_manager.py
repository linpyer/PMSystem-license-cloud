from __future__ import annotations

import os
import sys
import tempfile
import logging
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager, normalize_appearance_config
from app.core.voice_prompt import VoicePrompt
from app.theme.theme_manager import ThemeManager
from app.ui.dialog_utils import DialogSizeManager
from app.ui.settings_dialog import SettingsDialog


def main() -> int:
    assert normalize_appearance_config(None) == {"theme": "system"}
    assert normalize_appearance_config({"theme": "DARK"}) == {"theme": "dark"}
    assert normalize_appearance_config({"theme": "invalid"}) == {"theme": "system"}

    with tempfile.TemporaryDirectory() as temporary_dir:
        manager = ConfigManager(Path(temporary_dir))
        config = manager.load()
        assert config["appearance"]["theme"] == "system"
        assert "appearance" in manager._exportable_settings()

        app = QApplication.instance() or QApplication([])
        theme_manager = ThemeManager(app, manager)
        theme_manager.apply_configured_theme()
        assert theme_manager.current_mode() == "system"
        assert theme_manager.resolved_theme() in {"light", "dark"}

        theme_manager.preview_theme("dark")
        assert theme_manager.current_mode() == "dark"
        theme_manager.cancel_preview()
        assert theme_manager.current_mode() == "system"

        theme_manager.preview_theme("light")
        theme_manager.commit_theme("light")
        manager.update({"appearance": {"theme": theme_manager.current_mode()}})
        assert manager.config["appearance"]["theme"] == "light"

        reloaded = ConfigManager(Path(temporary_dir))
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
            dialog.theme_mode_buttons["dark"].click()
            assert theme_manager.current_mode() == "dark"
            dialog.reject()
            assert theme_manager.current_mode() == "system"

            reopened_dialog = SettingsDialog(
                config_manager=manager,
                logger=logging.getLogger("theme-test"),
                voice_prompt=VoicePrompt(manager.config, logging.getLogger("theme-test")),
                is_recording_callback=lambda: False,
                is_syncing_callback=lambda: False,
                theme_manager=theme_manager,
            )
            assert reopened_dialog.theme_mode_buttons["system"].isChecked()
            reopened_dialog.reject()

    print("theme manager tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
