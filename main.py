from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager
from app.core.logger import setup_logging
from app.core.version import APP_NAME, APP_VERSION
from app.ui.main_window import MainWindow
from app.ui.styles import APP_STYLES
from app.utils.runtime_paths import app_dir, resource_path, user_data_dir


APP_TITLE = APP_NAME


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

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    icon_path = resource_path("app/assets/logo.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(APP_STYLES)

    window = MainWindow(config_manager=config_manager, logger=logger)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
