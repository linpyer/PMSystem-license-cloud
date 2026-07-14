from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollBar,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import ConfigManager
from app.core.disk_space_checker import DiskSpaceChecker
from app.core.video_checker import VideoChecker
from app.core.video_player import open_folder
from app.core.version import APP_NAME
from app.ui.confirm_dialog import confirm_action
from app.ui.dialog_utils import DialogSizeManager
from app.ui.help_dialog import HelpDialog
from app.ui.monitor_tab import MonitorTab, is_camera_status_message
from app.ui.query_tab import QueryTab
from app.ui.settings_dialog import SettingsDialog
from app.ui.stats_dialog import PackagingStatsDialog
from app.ui.toast import ToastManager
from app.utils.runtime_paths import resource_path


APP_TITLE = APP_NAME
DEFAULT_WINDOW_WIDTH = 1600
DEFAULT_WINDOW_HEIGHT = 960
MIN_WINDOW_WIDTH = 1360
MIN_WINDOW_HEIGHT = 860
SILENT_MONITOR_MESSAGES = {
    "配置保存成功",
    "配置已保存",
    "视频存储目录已更新",
}
SILENT_MONITOR_MESSAGE_PREFIXES = (
    "录制类型已切换",
    "录制类型已更新",
)


class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager, logger: logging.Logger, theme_manager=None) -> None:
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.config_manager = config_manager
        self.logger = logger
        self.theme_manager = theme_manager
        self.help_dialog: HelpDialog | None = None
        self.settings_dialog: SettingsDialog | None = None
        self.stats_dialog: PackagingStatsDialog | None = None
        self._last_video_root_dir = str(self.config_manager.get_video_dir())
        self._window_drag_offset: QPoint | None = None
        self._resolved_theme = "light"
        self._toast_manager = ToastManager(self, self.logger)

        self.setWindowTitle(APP_TITLE)
        icon_path = resource_path("app/assets/app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget(self)
        central.setObjectName("mainWindowRoot")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("mainNavigation")
        self.tabs.setDocumentMode(True)
        self.monitor_tab = MonitorTab(config_manager=config_manager, logger=logger, parent=self)
        self.query_tab = QueryTab(config_manager=config_manager, logger=logger, parent=self)

        self.tabs.addTab(self.monitor_tab, "打包监控")
        self.tabs.addTab(self.query_tab, "视频查询")
        self._setup_help_entry()
        self._toast_manager.watch_position_sources(self.tabs.tabBar(), self.navigation_actions)
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(self._apply_navigation_icons)
            self._apply_navigation_icons(self.theme_manager.current_mode(), self.theme_manager.resolved_theme())
        central_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self._init_window_geometry()

        self.monitor_tab.status_message.connect(self._on_monitor_status_message)
        self.monitor_tab.warning_message.connect(lambda message: self._show_notice_banner(message, "warning"))
        self.monitor_tab.critical_message.connect(lambda message: self._show_notice_banner(message, "critical"))
        self.monitor_tab.recorder.recording_state_changed.connect(self._sync_settings_recording_state)
        self.monitor_tab.recorder.recording_state_changed.connect(self.query_tab.on_recording_state_changed)
        self.query_tab.video_list_changed.connect(self._on_query_video_list_changed)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        QTimer.singleShot(100, self._check_startup_disk_space)
        QTimer.singleShot(500, self._check_unfinished_recordings)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.monitor_tab.is_recording:
            if not confirm_action(
                self,
                title="确认退出",
                heading="当前正在录制，是否结束并保存？",
                description="退出程序会先结束当前录制并保存已录制内容。",
                confirm_text="结束录制并退出",
                destructive=True,
            ):
                event.ignore()
                return

        if self.query_tab.is_netdisk_syncing():
            if not confirm_action(
                self,
                title="确认退出",
                heading="当前正在同步网盘，是否继续关闭？",
                description="关闭软件会安全停止当前同步任务，尚未完成的文件可稍后重试。",
                confirm_text="停止同步并退出",
                destructive=True,
            ):
                event.ignore()
                return

        self.monitor_tab.shutdown()
        self.query_tab.shutdown()
        self._save_window_geometry()
        event.accept()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._apply_window_control_icons()
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(100, self._restore_monitor_focus)

    def _init_window_geometry(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
            self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            self.logger.info("主窗口默认尺寸初始化：%sx%s", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            return

        available = screen.availableGeometry()
        available_width = max(1, available.width())
        available_height = max(1, available.height())
        fallback_width = int(available_width * 0.92)
        fallback_height = int(available_height * 0.92)

        min_width = min(MIN_WINDOW_WIDTH, max(1024, fallback_width))
        min_height = min(MIN_WINDOW_HEIGHT, max(720, fallback_height))
        self.setMinimumSize(min_width, min_height)

        default_width = DEFAULT_WINDOW_WIDTH if available_width >= DEFAULT_WINDOW_WIDTH else max(min_width, fallback_width)
        default_height = DEFAULT_WINDOW_HEIGHT if available_height >= DEFAULT_WINDOW_HEIGHT else max(min_height, fallback_height)
        width = default_width
        height = default_height
        use_saved_position = False

        window_config = self.config_manager.config.get("window", {})
        if (
            isinstance(window_config, dict)
            and bool(window_config.get("remember_geometry", True))
            and bool(window_config.get("geometry_saved", False))
        ):
            try:
                saved_width = int(window_config.get("width", 0) or 0)
                saved_height = int(window_config.get("height", 0) or 0)
                if saved_width >= MIN_WINDOW_WIDTH and saved_height >= MIN_WINDOW_HEIGHT:
                    width = min(max(saved_width, min_width), available_width)
                    height = min(max(saved_height, min_height), available_height)
                    use_saved_position = True
                elif saved_width > 0 or saved_height > 0:
                    self.logger.info(
                        "保存的主窗口尺寸过小，已回退默认尺寸：saved=%sx%s, default=%sx%s",
                        saved_width,
                        saved_height,
                        default_width,
                        default_height,
                    )
            except (TypeError, ValueError):
                self.logger.warning("保存的主窗口尺寸不可用，已回退默认尺寸")

        self.resize(width, height)

        x = available.x() + (available.width() - width) // 2
        y = available.y() + (available.height() - height) // 2
        if use_saved_position:
            try:
                saved_x = int(window_config.get("x", x))
                saved_y = int(window_config.get("y", y))
                max_x = available.x() + max(0, available.width() - width)
                max_y = available.y() + max(0, available.height() - height)
                if available.x() <= saved_x <= max_x and available.y() <= saved_y <= max_y:
                    x = saved_x
                    y = saved_y
                    self.logger.info("恢复上次主窗口大小和位置：%sx%s, x=%s, y=%s", width, height, x, y)
                else:
                    self.logger.info("保存的主窗口位置超出当前屏幕，已回退居中显示")
            except (TypeError, ValueError):
                self.logger.warning("保存的主窗口位置不可用，已回退居中显示")
        else:
            self.logger.info("主窗口默认尺寸初始化：%sx%s", width, height)

        self.move(x, y)

    def _save_window_geometry(self) -> None:
        try:
            geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
            values = {
                "window": {
                    "width": max(self.minimumWidth(), geometry.width()),
                    "height": max(self.minimumHeight(), geometry.height()),
                    "x": geometry.x(),
                    "y": geometry.y(),
                    "remember_geometry": True,
                    "geometry_saved": True,
                }
            }
            self.config_manager.update(values)
            self.logger.info(
                "保存主窗口大小和位置：%sx%s, x=%s, y=%s",
                values["window"]["width"],
                values["window"]["height"],
                values["window"]["x"],
                values["window"]["y"],
            )
        except Exception:
            self.logger.exception("保存主窗口大小和位置失败")

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.query_tab:
            QTimer.singleShot(0, self.query_tab.activate)
        elif self.tabs.widget(index) is self.monitor_tab:
            QTimer.singleShot(0, self._restore_monitor_focus)

    def _on_query_video_list_changed(self, reason: str) -> None:
        if reason == "deleted":
            QTimer.singleShot(0, self.monitor_tab.refresh_recent_recordings)

    def _setup_help_entry(self) -> None:
        corner = QWidget(self)
        corner.setObjectName("navigationActions")
        self.navigation_actions = corner
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 12, 0)
        corner_layout.setSpacing(8)

        self.stats_button = QToolButton(self)
        self.stats_button.setObjectName("statsButton")
        self.stats_button.setToolTip("打包发货统计")
        self.stats_button.setFocusPolicy(Qt.NoFocus)
        self.stats_button.clicked.connect(self._show_stats_dialog)

        self.settings_button = QToolButton(self)
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setToolTip("设置")
        self.settings_button.setFocusPolicy(Qt.NoFocus)
        self.settings_button.clicked.connect(self._show_settings_dialog)

        self.help_button = QToolButton(self)
        self.help_button.setObjectName("helpIconButton")
        self.help_button.setToolTip("使用说明")
        self.help_button.setFocusPolicy(Qt.NoFocus)
        self.help_button.clicked.connect(self._show_help_dialog)
        self.window_min_button = QToolButton(self)
        self.window_min_button.setObjectName("windowMinButton")
        self.window_min_button.setToolTip("最小化")
        self.window_min_button.setFocusPolicy(Qt.NoFocus)
        self.window_min_button.clicked.connect(self.showMinimized)

        self.window_max_button = QToolButton(self)
        self.window_max_button.setObjectName("windowMaxButton")
        self.window_max_button.setToolTip("最大化")
        self.window_max_button.setFocusPolicy(Qt.NoFocus)
        self.window_max_button.clicked.connect(self._toggle_maximized)

        self.window_close_button = QToolButton(self)
        self.window_close_button.setObjectName("windowCloseButton")
        self.window_close_button.setToolTip("关闭")
        self.window_close_button.setFocusPolicy(Qt.NoFocus)
        self.window_close_button.clicked.connect(self.close)
        corner_layout.addWidget(self.stats_button)
        corner_layout.addWidget(self.settings_button)
        corner_layout.addWidget(self.help_button)
        corner_layout.addSpacing(4)
        corner_layout.addWidget(self.window_min_button)
        corner_layout.addWidget(self.window_max_button)
        corner_layout.addWidget(self.window_close_button)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)

    def toast_titlebar_available_rect(self) -> QRect:
        """Return the overlay-only gap between navigation tabs and title-bar actions."""
        tab_bar = self.tabs.tabBar()
        tab_count = tab_bar.count()
        if tab_count:
            left_edge = tab_bar.mapTo(self, QPoint(tab_bar.tabRect(tab_count - 1).right() + 1, 0)).x()
        else:
            left_edge = tab_bar.mapTo(self, QPoint(0, 0)).x()
        actions_top_left = self.navigation_actions.mapTo(self, QPoint(0, 0))
        tab_top_left = tab_bar.mapTo(self, QPoint(0, 0))
        available_left = left_edge + 14
        available_right = actions_top_left.x() - 14
        top = min(tab_top_left.y(), actions_top_left.y())
        bottom = max(
            tab_top_left.y() + tab_bar.height(),
            actions_top_left.y() + self.navigation_actions.height(),
        )
        return QRect(available_left, top, max(0, available_right - available_left), max(1, bottom - top))

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        return super().eventFilter(watched, event)

    def nativeEvent(self, event_type, message):  # type: ignore[override]
        """Delegate frameless window dragging and resizing to Windows' native hit test."""
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    result = self._window_hit_test(self.mapFromGlobal(QCursor.pos()))
                    if result != 1:  # HTCLIENT
                        return True, result
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        return super().nativeEvent(event_type, message)

    def _window_hit_test(self, point: QPoint) -> int:
        """Return the Windows non-client hit-test result for a logical Qt position."""
        HTCLIENT, HTCAPTION = 1, 2
        HTLEFT, HTRIGHT, HTTOP, HTBOTTOM = 10, 11, 12, 15
        HTTOPLEFT, HTTOPRIGHT, HTBOTTOMLEFT, HTBOTTOMRIGHT = 13, 14, 16, 17
        if self.isMaximized():
            return HTCLIENT

        margin = 8
        rect = self.rect()
        on_left = point.x() < margin
        on_right = point.x() >= rect.width() - margin
        on_top = point.y() < margin
        on_bottom = point.y() >= rect.height() - margin
        if on_top and on_left:
            return HTTOPLEFT
        if on_top and on_right:
            return HTTOPRIGHT
        if on_bottom and on_left:
            return HTBOTTOMLEFT
        if on_bottom and on_right:
            return HTBOTTOMRIGHT
        if on_left:
            return HTLEFT
        if on_right:
            return HTRIGHT
        if on_top:
            return HTTOP
        if on_bottom:
            return HTBOTTOM

        tab_bar = self.tabs.tabBar()
        tab_bar_bottom = self.tabs.mapTo(self, QPoint(0, 0)).y() + tab_bar.height()
        if point.y() < tab_bar_bottom and not self._is_interactive_title_target(point):
            return HTCAPTION
        return HTCLIENT

    def _is_interactive_title_target(self, point: QPoint) -> bool:
        widget = self.childAt(point)
        while widget is not None and widget is not self:
            if isinstance(widget, QTabBar):
                if widget.tabAt(widget.mapFrom(self, point)) >= 0:
                    return True
            elif isinstance(widget, (QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QAbstractItemView, QScrollBar)):
                return True
            widget = widget.parentWidget()
        return False

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.window_max_button.setToolTip("最大化")
        else:
            self.showMaximized()
            self.window_max_button.setToolTip("恢复")
        self._apply_window_control_icons()

    def _apply_navigation_icons(self, _mode: str = "system", resolved_theme: str = "light") -> None:
        self._resolved_theme = resolved_theme
        suffix = "-light" if resolved_theme == "dark" else ""
        icon_specs = (
            (self.stats_button, f"app/assets/icons/chart-bars{suffix}.svg", QSize(18, 18)),
            (self.settings_button, f"app/assets/icons/settings{suffix}.svg", QSize(19, 19)),
            (self.help_button, f"app/assets/icons/circle-help{suffix}.svg", QSize(19, 19)),
        )
        for button, relative_path, size in icon_specs:
            icon_path = resource_path(relative_path)
            if icon_path.exists():
                button.setText("")
                button.setIcon(QIcon(str(icon_path)))
                button.setIconSize(size)
            else:
                button.setIcon(QIcon())
                button.setText("?" if button is self.help_button else "")
        self._apply_window_control_icons()
        QTimer.singleShot(0, self._toast_manager.reposition)

    def _apply_window_control_icons(self) -> None:
        if not hasattr(self, "window_min_button"):
            return
        suffix = "-light" if self._resolved_theme == "dark" else ""
        max_icon = "window-restore" if self.isMaximized() else "window-maximize"
        specs = (
            (self.window_min_button, "window-minimize"),
            (self.window_max_button, max_icon),
            (self.window_close_button, "window-close"),
        )
        for button, icon_name in specs:
            path = resource_path(f"app/assets/icons/{icon_name}{suffix}.svg")
            button.setIcon(QIcon(str(path)) if path.exists() else QIcon())
            button.setIconSize(QSize(18, 18))

    def _show_stats_dialog(self) -> None:
        self.logger.info("用户打开打包发货统计弹窗")
        if self.stats_dialog is None:
            self.stats_dialog = PackagingStatsDialog(
                database=self.query_tab.database,
                notice_callback=self.show_status_tip,
                parent=self,
            )
        self.stats_dialog.show()
        self.stats_dialog.raise_()
        self.stats_dialog.activateWindow()

    def _show_settings_dialog(self) -> None:
        self.logger.info("open_settings: clicked")
        try:
            if self.settings_dialog is not None and self.settings_dialog.isVisible():
                self.logger.info("open_settings: existing dialog visible")
                self.settings_dialog.raise_()
                self.settings_dialog.activateWindow()
                return

            if self.settings_dialog is None:
                self.logger.info("open_settings: creating dialog")
                self.settings_dialog = SettingsDialog(
                    config_manager=self.config_manager,
                    logger=self.logger,
                    voice_prompt=self.monitor_tab.voice_prompt,
                    is_recording_callback=lambda: self.monitor_tab.is_recording,
                    is_syncing_callback=lambda: self.query_tab.is_netdisk_syncing(),
                    theme_manager=self.theme_manager,
                    parent=self,
                )
                self.settings_dialog.config_saved.connect(self.monitor_tab.apply_external_config)
                self.settings_dialog.config_saved.connect(self.query_tab.reload_config)
                self.settings_dialog.basic_config_saved.connect(self.monitor_tab.apply_basic_config)
                self.settings_dialog.basic_config_saved.connect(self.query_tab.reload_config)
                self.settings_dialog.basic_config_saved.connect(self._on_basic_config_saved)
                self.settings_dialog.closed.connect(self._restore_monitor_focus)
                self.settings_dialog.destroyed.connect(self._on_settings_dialog_destroyed)
                self.logger.info("open_settings: dialog created")
            elif not self.settings_dialog.isVisible():
                self.settings_dialog.begin_theme_preview_session()

            self.settings_dialog.refresh_state(self.monitor_tab.is_recording)
            self.logger.info("open_settings: showing dialog")
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
        except Exception:
            self.logger.exception("打开设置窗口失败")
            traceback.print_exc()
            self.settings_dialog = None
            self.show_status_tip("设置窗口打开失败，请查看日志", "error", 5000)

    def _show_help_dialog(self) -> None:
        self.logger.info("用户打开使用说明页签窗口")
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self)
            self.help_dialog.closed.connect(self._on_help_dialog_closed)

        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def _sync_settings_recording_state(self, recording: bool, _order_id: str, _start_time: str) -> None:
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.refresh_state(recording)

    def _on_basic_config_saved(self, _config: dict) -> None:
        current_dir = str(self.config_manager.get_video_dir())
        if current_dir != self._last_video_root_dir:
            self._last_video_root_dir = current_dir
            self.show_status_tip("视频存储目录已更新", "success", 4000)

    def _on_help_dialog_closed(self) -> None:
        self.logger.info("用户关闭使用说明页签窗口")
        QTimer.singleShot(0, self._restore_monitor_focus)

    def _on_settings_dialog_destroyed(self, _obj=None) -> None:
        self.settings_dialog = None
        QTimer.singleShot(0, self._restore_monitor_focus)

    def _restore_monitor_focus(self) -> None:
        if self.tabs.currentWidget() is self.monitor_tab:
            self.monitor_tab.focus_scan_input()

    def _check_startup_disk_space(self) -> None:
        disk_config = self.config_manager.config.get("disk_space", {})
        if isinstance(disk_config, dict) and not bool(disk_config.get("enabled", True)):
            return

        result = DiskSpaceChecker(self.config_manager.config, self.logger).check(self.config_manager.get_video_dir())
        if result.level == "critical":
            self._show_notice_banner(result.message, "critical", timeout_ms=15000)
        elif result.level == "warning":
            self._show_notice_banner(result.message, "warning", timeout_ms=12000)
        elif result.level == "error":
            self.logger.warning(result.message)

    def _show_notice_banner(self, message: str, level: str = "info", timeout_ms: int = 10000) -> None:
        self.show_status_tip(message, level, timeout_ms)

    def _on_monitor_status_message(self, message: str) -> None:
        if is_camera_status_message(message):
            self.logger.info("摄像头持续状态已从 Toast 入口过滤：%s", message)
            return
        if self._is_video_data_changed_message(message):
            self.query_tab.mark_dirty()
        self.query_tab.on_recording_status_message(message)
        if self._is_silent_monitor_message(message):
            self.logger.debug("监控页静默成功提示已忽略：%s", message)
            return
        timeout_ms = 4000
        self.show_status_tip(message, "info", timeout_ms)

    @staticmethod
    def _is_silent_monitor_message(message: str) -> bool:
        text = (message or "").strip()
        if text in SILENT_MONITOR_MESSAGES:
            return True
        return any(text.startswith(prefix) for prefix in SILENT_MONITOR_MESSAGE_PREFIXES)

    @staticmethod
    def _is_video_data_changed_message(message: str) -> bool:
        text = (message or "").strip()
        return any(
            keyword in text
            for keyword in (
                "视频已保存",
                "视频保存异常",
                "视频文件不存在，校验失败",
                "视频已删除",
                "记录已移除",
            )
        )

    def show_status_tip(self, message: str, level: str = "info", timeout_ms: int = 3000) -> None:
        if not message:
            return
        normalized_level = level if level in {"success", "info", "warning", "error", "critical"} else "info"
        self._toast_manager.show(message, normalized_level, max(2400, int(timeout_ms)))

    def _show_toast(self, message: str, level: str = "info", timeout_ms: int = 3000) -> None:
        self.show_status_tip(message, level, timeout_ms)

    def _check_unfinished_recordings(self) -> None:
        video_dir = self.config_manager.get_video_dir()
        unfinished = VideoChecker(self.logger).scan_unfinished_files(video_dir)
        if not unfinished:
            return

        preview = "\n".join(path.name for path in unfinished[:8])
        if len(unfinished) > 8:
            preview += f"\n等 {len(unfinished)} 个文件"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("发现未完成录制文件")
        box.setText("检测到上次可能异常退出留下的临时录制文件。")
        box.setInformativeText(f"{preview}\n\n程序不会自动删除这些文件，请人工确认后处理。")
        open_button = box.addButton("打开视频文件夹", QMessageBox.ActionRole)
        box.addButton("稍后处理", QMessageBox.AcceptRole)
        DialogSizeManager.position_transient(box, self)
        box.exec()

        if box.clickedButton() is open_button:
            try:
                open_folder(video_dir)
            except Exception as exc:
                self.logger.exception("打开视频文件夹失败")
                self._show_notice_banner(f"打开失败：{exc}", "error")
