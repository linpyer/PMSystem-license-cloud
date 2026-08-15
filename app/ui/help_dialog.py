from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QStackedWidget,
    QTabBar,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.theme.theme_tokens import LIGHT_TOKENS
from app.ui.dialog_utils import DialogSizeManager
from app.ui.theme_icons import themed_svg_icon


def build_help_style() -> str:
    """Build browser CSS from the active application theme."""
    app = QApplication.instance()
    manager = app.property("theme_manager") if app is not None else None
    tokens = manager.current_tokens() if manager is not None else LIGHT_TOKENS
    return f"""
body {{
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    color: {tokens.text_primary};
    background: transparent;
    line-height: 1.72;
    font-size: 14px;
    margin: 0;
}}
h1 {{
    font-size: 20px;
    margin: 4px 0 14px 0;
    color: {tokens.text_primary};
}}
h2 {{
    font-size: 16px;
    margin: 18px 0 8px 0;
    color: {tokens.text_secondary};
}}
ol {{
    margin: 0 0 0 22px;
    padding: 0;
}}
li {{
    margin: 5px 0;
}}
p {{
    margin: 7px 0;
}}
.question {{
    font-weight: 700;
    color: {tokens.text_primary};
    margin-top: 13px;
}}
.note {{
    background: {tokens.surface_secondary};
    border: 1px solid {tokens.border};
    border-radius: 8px;
    padding: 10px 12px;
    color: {tokens.text_secondary};
    margin-top: 10px;
}}
"""


HELP_TABS: list[tuple[str, str]] = [
    (
        "快速开始",
        """
        <h1>快速开始</h1>
        <ol>
        <li>选择需要使用的摄像头，并确认预览画面正常。</li>
        <li>在设置中选择视频保存目录，确认目录可正常写入。</li>
        <li>选择发货或退货录制类型。</li>
        <li>保持扫码输入框可接收扫码枪输入。</li>
        <li>扫描有效订单号后，软件会开始录制。</li>
        </ol>
        """,
    ),
    (
        "7天免费试用",
        """
        <h1>7天免费试用</h1>
        <ol>
        <li>首次使用软件会自动尝试开启7天免费试用。</li>
        <li>试用时间为首次成功开启后的168小时。</li>
        <li>试用期间可正常使用录制、查询、播放和上传功能。</li>
        <li>首次开启试用需要连接网络。</li>
        <li>没有网络时仍可进入软件查看已有记录，联网后可重试开启试用。</li>
        <li>也可以直接输入正式激活码。</li>
        </ol>
        """,
    ),
    (
        "扫码录制",
        """
        <h1>扫码录制规则</h1>
        <ol>
        <li>空闲状态扫描有效订单号：开始录制。</li>
        <li>正在录制时扫描相同订单号：结束当前录制，不开始新的录制。</li>
        <li>正在录制时扫描不同订单号：结束并保存上一个订单，自动开始新订单录制。</li>
        <li>正在录制时输入空内容或触发空扫码：结束当前录制，不开始新的录制。</li>
        </ol>
        """,
    ),
    (
        "录制与水印",
        """
        <h1>发货、退货与视频水印</h1>
        <ol>
        <li>开始录制前选择发货或退货。</li>
        <li>当前录制类型会保存到记录中，并可在查询页面筛选。</li>
        <li>视频按订单号保存，并包含订单号和录制时间水印。</li>
        <li>保存目录可在设置中配置。</li>
        <li>正在录制时不要直接关闭电脑或拔掉摄像头。</li>
        </ol>
        """,
    ),
    (
        "历史查询",
        """
        <h1>历史查询与播放</h1>
        <ol>
        <li>可以按订单号、日期和录制类型查询。</li>
        <li>可以播放、定位和查看视频详情。</li>
        <li>授权失效后，历史查询与视频播放仍可使用。</li>
        <li>删除视频属于不可恢复操作，请在确认内容无误后再执行。</li>
        </ol>
        """,
    ),
    (
        "授权和激活",
        """
        <h1>授权和激活</h1>
        <ol>
        <li>免费试用结束后仍可进入软件，但不能开始新的录制或上传任务。</li>
        <li>未授权时尝试开始录制，软件会自动打开激活窗口。</li>
        <li>输入有效激活码后即可恢复完整功能。</li>
        <li>激活成功后，可以选择是否继续刚才的订单录制。</li>
        <li>“软件授权”页面支持立即验证和设备解绑。</li>
        </ol>
        """,
    ),
    (
        "授权失效",
        """
        <h1>授权失效后的使用范围</h1>
        <ol>
        <li>授权失效不会删除历史记录、视频或软件配置。</li>
        <li>查询、筛选和视频播放仍可使用。</li>
        <li>新的录制和上传任务会被阻止。</li>
        <li>重新激活或在线验证成功后会恢复完整功能。</li>
        <li>正在进行的录制会安全完成，不会因授权状态变化被强制截断。</li>
        </ol>
        """,
    ),
    (
        "摄像头问题",
        """
        <h1>摄像头问题</h1>
        <ol>
        <li>检查摄像头是否被其他软件占用。</li>
        <li>点击刷新摄像头并重新选择设备。</li>
        <li>检查USB连接是否稳定。</li>
        <li>问题仍未解决时，关闭占用摄像头的软件后重新启动 DD Rec。</li>
        </ol>
        """,
    ),
    (
        "视频保存",
        """
        <h1>视频保存问题</h1>
        <ol>
        <li>确认保存目录存在，并且磁盘空间充足。</li>
        <li>确认当前Windows用户对保存目录有写入权限。</li>
        <li>不建议把视频保存目录设置为系统临时目录。</li>
        <li>录制完成后请等待视频保存结束，再关闭软件。</li>
        </ol>
        """,
    ),
    (
        "语音提示",
        """
        <h1>语音提示</h1>
        <ol>
        <li>可以在设置中开启或关闭语音提示。</li>
        <li>可以测试开始录制和结束录制提示。</li>
        <li>使用本地语音包时，请保持所需语音文件完整存在。</li>
        </ol>
        """,
    ),
    (
        "安全退出",
        """
        <h1>安全退出</h1>
        <ol>
        <li>正在录制时，先结束当前录制。</li>
        <li>等待视频保存完成后再关闭软件。</li>
        <li>不要在视频写入过程中强制结束 DD Rec 进程。</li>
        <li>不要在录制过程中直接关闭电脑或拔掉存储设备。</li>
        </ol>
        """,
    ),
]


class HelpDialog(QDialog):
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("helpDialog")
        self.setWindowTitle("使用说明")
        self.setWindowModality(Qt.NonModal)
        DialogSizeManager.apply(self, "help", parent, "medium", (660, 480))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        navigation = QWidget(self)
        navigation.setObjectName("helpNavigation")
        navigation.setMinimumHeight(56)
        navigation_layout = QHBoxLayout(navigation)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(8)
        navigation_layout.setAlignment(Qt.AlignVCenter)

        self.previous_button = QToolButton(navigation)
        self.previous_button.setObjectName("helpPrevButton")
        self.previous_button.setToolTip("上一页")
        self.previous_button.setAccessibleName("上一页")
        self.previous_button.setFixedSize(36, 36)
        self.previous_button.setIconSize(QSize(17, 17))
        self.previous_button.clicked.connect(lambda: self._change_page(-1))

        self.help_tab_bar = QTabBar(navigation)
        self.help_tab_bar.setObjectName("helpTabBar")
        self.help_tab_bar.setUsesScrollButtons(False)
        self.help_tab_bar.setExpanding(False)
        self.help_tab_bar.setElideMode(Qt.ElideRight)

        self.next_button = QToolButton(navigation)
        self.next_button.setObjectName("helpNextButton")
        self.next_button.setToolTip("下一页")
        self.next_button.setAccessibleName("下一页")
        self.next_button.setFixedSize(36, 36)
        self.next_button.setIconSize(QSize(17, 17))
        self.next_button.clicked.connect(lambda: self._change_page(1))

        navigation_layout.addWidget(self.previous_button, 0, Qt.AlignVCenter)
        navigation_layout.addWidget(self.help_tab_bar, 1, Qt.AlignVCenter)
        navigation_layout.addWidget(self.next_button, 0, Qt.AlignVCenter)
        layout.addWidget(navigation)

        self.tabs = QStackedWidget(self)
        self.tabs.setObjectName("helpPages")
        for title, html in HELP_TABS:
            self.help_tab_bar.addTab(title)
            self.tabs.addWidget(self._create_tab(html))
        self.help_tab_bar.currentChanged.connect(self._set_current_page)
        layout.addWidget(self.tabs, 1)
        app = QApplication.instance()
        manager = app.property("theme_manager") if app is not None else None
        if manager is not None:
            manager.theme_changed.connect(self._refresh_theme)
        self._refresh_navigation_icons()
        self._update_navigation_buttons()

    def _create_tab(self, html: str) -> QTextBrowser:
        browser = QTextBrowser(self)
        browser.setObjectName("helpContent")
        browser.setOpenExternalLinks(False)
        browser.setProperty("helpHtml", html)
        browser.setHtml(f'<!doctype html><html><head><meta charset="utf-8"><style>{build_help_style()}</style></head><body>{html}</body></html>')
        return browser

    def _refresh_theme(self, *_args) -> None:
        for browser in self.tabs.findChildren(QTextBrowser):
            html = str(browser.property("helpHtml") or "")
            position = browser.verticalScrollBar().value()
            browser.setHtml(f'<!doctype html><html><head><meta charset="utf-8"><style>{build_help_style()}</style></head><body>{html}</body></html>')
            browser.verticalScrollBar().setValue(position)
        self._refresh_navigation_icons()

    def _set_current_page(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)
        self._update_navigation_buttons()

    def _change_page(self, offset: int) -> None:
        target = max(0, min(self.help_tab_bar.count() - 1, self.help_tab_bar.currentIndex() + offset))
        self.help_tab_bar.setCurrentIndex(target)

    def _update_navigation_buttons(self) -> None:
        index = self.help_tab_bar.currentIndex()
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < self.help_tab_bar.count() - 1)

    def _refresh_navigation_icons(self) -> None:
        app = QApplication.instance()
        manager = app.property("theme_manager") if app is not None else None
        self.previous_button.setIcon(themed_svg_icon("chevron-left", manager, 17))
        self.next_button.setIcon(themed_svg_icon("chevron-right", manager, 17))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        DialogSizeManager.remember(self, "help")
        self.closed.emit()
        super().closeEvent(event)
