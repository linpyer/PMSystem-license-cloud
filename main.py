from __future__ import annotations

import sys
import ctypes

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager
from app.core.logger import setup_logging
from app.core.version import APP_NAME, APP_VERSION
from app.licensing.constants import LicenseStatus
from app.licensing.license_manager import LicenseManager
from app.theme.theme_manager import ThemeManager
from app.ui.main_window import MainWindow
from app.utils.runtime_paths import app_dir, resource_path, user_data_dir


APP_TITLE = APP_NAME
APP_ICON_PATH = "app/assets/app_icon.ico"
APP_USER_MODEL_ID = "JsonLin.PMSystem"


def _license_requires_activation(_status: LicenseStatus) -> bool:
    """Startup is never blocked; activation is opened only when the user needs it."""
    return False


def _set_windows_app_user_model_id() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        if result != 0:
            return f"HRESULT=0x{int(result) & 0xFFFFFFFF:08X}"
    except Exception as exc:
        return str(exc)
    return None


def _load_application_icon() -> tuple[QIcon | None, str, str | None]:
    icon_path = resource_path(APP_ICON_PATH)
    if not icon_path.is_file():
        return None, str(icon_path), "图标文件不存在"
    icon = QIcon(str(icon_path))
    if icon.isNull():
        return None, str(icon_path), "QIcon 加载结果为空"
    return icon, str(icon_path), None


def main() -> int:
    app_user_model_id_error = _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    application_icon, icon_path, icon_error = _load_application_icon()
    if application_icon is not None:
        app.setWindowIcon(application_icon)

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
    if app_user_model_id_error:
        logger.error("Windows AppUserModelID 设置失败：id=%s, error=%s", APP_USER_MODEL_ID, app_user_model_id_error)
    else:
        logger.info("Windows AppUserModelID 已设置：%s", APP_USER_MODEL_ID)
    if icon_error:
        logger.error("应用图标加载失败：path=%s, error=%s", icon_path, icon_error)
    else:
        logger.info("应用图标加载成功：%s", icon_path)
    theme_manager = ThemeManager(app, config_manager)
    app.setProperty("theme_manager", theme_manager)
    theme_manager.apply_configured_theme()

    try:
        license_manager = LicenseManager(logger=logger)
        license_status = license_manager.initialize()
    except Exception:
        logger.exception("授权模块初始化失败")
        return 1

    window = MainWindow(
        config_manager=config_manager,
        logger=logger,
        theme_manager=theme_manager,
        license_manager=license_manager,
    )
    if application_icon is not None:
        window.setWindowIcon(application_icon)
    window.show()
    QTimer.singleShot(0, window.start_license_background_verification)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
