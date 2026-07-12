from __future__ import annotations

import sys
import ctypes

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager
from app.core.logger import setup_logging
from app.core.version import APP_NAME, APP_VERSION
from app.theme.theme_manager import ThemeManager
from app.ui.main_window import MainWindow
from app.utils.runtime_paths import app_dir, resource_path, user_data_dir


APP_TITLE = APP_NAME
APP_ICON_PATH = "app/assets/app_icon.ico"
APP_USER_MODEL_ID = "PMSystem.PackagingTrace.Monitor"


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        return


def main() -> int:
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(data_dir)
    config_manager.load()

    logger = setup_logging(data_dir)
    logger.info("程序启动")
    logger.info("程序版本：%s", APP_VERSION)
    logger.info("程序目录：%s", app_dir())
    logger.info("用户数据目录：%s", data_dir)
    logger.info("database_path=%s", config_manager.database_path)
    logger.info("video_root_dir=%s", config_manager.get_video_dir())

    _set_windows_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    icon_path = resource_path(APP_ICON_PATH)
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    theme_manager = ThemeManager(app, config_manager)
    app.setProperty("theme_manager", theme_manager)
    theme_manager.apply_configured_theme()

    window = MainWindow(config_manager=config_manager, logger=logger, theme_manager=theme_manager)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
