from __future__ import annotations

import logging
import time
import traceback

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import ConfigManager
from app.core.disk_space_checker import DiskSpaceChecker
from app.core.video_checker import VideoChecker
from app.core.video_player import open_folder
from app.core.version import APP_NAME, APP_VERSION
from app.ui.help_dialog import HelpDialog
from app.ui.monitor_tab import MonitorTab
from app.ui.query_tab import QueryTab
from app.ui.settings_dialog import SettingsDialog
from app.ui.stats_dialog import PackagingStatsDialog
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


class StatusTipLabel(QWidget):
    LEVEL_COLORS = {
        "success": QColor("#047857"),
        "info": QColor("#2563eb"),
        "warning": QColor("#d97706"),
        "error": QColor("#dc2626"),
        "critical": QColor("#dc2626"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusTipLabel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(160)
        self._text = ""
        self._level = "info"
        self._offset = 0
        self._gap = 36
        self._is_scrolling = False
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(45)
        self._scroll_timer.timeout.connect(self._advance_scroll)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        metrics = self.fontMetrics()
        return QSize(360, metrics.height() + 2)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        metrics = self.fontMetrics()
        return QSize(160, metrics.height() + 2)

    def set_tip(self, text: str, level: str = "info") -> None:
        self._scroll_timer.stop()
        self._text = text
        self._level = level if level in self.LEVEL_COLORS else "info"
        self._offset = 0
        self._update_scroll_state()
        self.update()

    def clear_tip(self) -> None:
        self._scroll_timer.stop()
        self._text = ""
        self._offset = 0
        self._is_scrolling = False
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_scroll_state()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setPen(self.LEVEL_COLORS.get(self._level, self.LEVEL_COLORS["info"]))
        metrics = painter.fontMetrics()
        baseline = (self.height() + metrics.ascent() - metrics.descent()) // 2
        text_width = metrics.horizontalAdvance(self._text)

        if not self._is_scrolling:
            painter.drawText(0, baseline, self._text)
            return

        x = -self._offset
        painter.drawText(x, baseline, self._text)
        painter.drawText(x + text_width + self._gap, baseline, self._text)

    def _update_scroll_state(self) -> None:
        if not self._text:
            self._is_scrolling = False
            self._scroll_timer.stop()
            return

        text_width = self.fontMetrics().horizontalAdvance(self._text)
        available_width = max(1, self.width())
        should_scroll = text_width > available_width
        self._is_scrolling = should_scroll
        if should_scroll and not self._scroll_timer.isActive():
            self._scroll_timer.start()
        elif not should_scroll:
            self._scroll_timer.stop()
            self._offset = 0

    def _advance_scroll(self) -> None:
        if not self._text:
            self.clear_tip()
            return
        text_width = self.fontMetrics().horizontalAdvance(self._text)
        self._offset = (self._offset + 2) % max(1, text_width + self._gap)
        self.update()


class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager, logger: logging.Logger, theme_manager=None) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.logger = logger
        self.theme_manager = theme_manager
        self.help_dialog: HelpDialog | None = None
        self.settings_dialog: SettingsDialog | None = None
        self.stats_dialog: PackagingStatsDialog | None = None
        self._last_toast_message = ""
        self._last_toast_time = 0.0
        self._last_video_root_dir = str(self.config_manager.get_video_dir())

        self.setWindowTitle(APP_TITLE)
        icon_path = resource_path("app/assets/app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.monitor_tab = MonitorTab(config_manager=config_manager, logger=logger, parent=self)
        self.query_tab = QueryTab(config_manager=config_manager, logger=logger, parent=self)

        self.tabs.addTab(self.monitor_tab, "打包监控")
        self.tabs.addTab(self.query_tab, "视频查询")
        self._setup_help_entry()
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
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._setup_status_tip()
        self.show_status_tip("系统已启动", "info", 2600)
        QTimer.singleShot(100, self._check_startup_disk_space)
        QTimer.singleShot(500, self._check_unfinished_recordings)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.monitor_tab.is_recording:
            result = QMessageBox.question(
                self,
                "确认退出",
                "当前正在录制，是否结束并保存？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if result != QMessageBox.Yes:
                event.ignore()
                return

        if self.query_tab.is_netdisk_syncing():
            result = QMessageBox.question(
                self,
                "确认退出",
                "当前正在同步网盘，关闭软件会中断上传，是否继续关闭？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                event.ignore()
                return

        self.monitor_tab.shutdown()
        self.query_tab.shutdown()
        self._save_window_geometry()
        event.accept()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
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

    def _setup_help_entry(self) -> None:
        corner = QWidget(self)
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
        corner_layout.addWidget(self.stats_button)
        corner_layout.addWidget(self.settings_button)
        corner_layout.addWidget(self.help_button)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)

    def _apply_navigation_icons(self, _mode: str = "system", resolved_theme: str = "light") -> None:
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

    def _setup_status_tip(self) -> None:
        self.status_tip_label = StatusTipLabel(self)
        self.version_label = QLabel(f"v{APP_VERSION}", self)
        self.version_label.setObjectName("statusVersionLabel")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.status_tip_timer = QTimer(self)
        self.status_tip_timer.setSingleShot(True)
        self.status_tip_timer.timeout.connect(self.status_tip_label.clear_tip)
        self.statusBar().addWidget(self.status_tip_label, 1)
        self.statusBar().addPermanentWidget(self.version_label)

    def show_status_tip(self, message: str, level: str = "info", timeout_ms: int = 3000) -> None:
        if not message:
            return
        now = time.monotonic()
        if message == self._last_toast_message and now - self._last_toast_time < 0.8:
            return
        self._last_toast_message = message
        self._last_toast_time = now
        normalized_level = level if level in {"success", "info", "warning", "error", "critical"} else "info"
        icon = {
            "success": "✓",
            "info": "i",
            "warning": "!",
            "error": "×",
            "critical": "×",
        }.get(normalized_level, "i")
        self.status_tip_timer.stop()
        self.status_tip_label.set_tip(f"{icon} {message}", normalized_level)
        self.status_tip_timer.start(max(800, int(timeout_ms)))

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
        box.exec()

        if box.clickedButton() is open_button:
            try:
                open_folder(video_dir)
            except Exception as exc:
                self.logger.exception("打开视频文件夹失败")
                self._show_notice_banner(f"打开失败：{exc}", "error")
