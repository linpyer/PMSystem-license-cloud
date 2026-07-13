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
        "基础流程",
        """
        <h1>基础使用流程</h1>
        <ol>
        <li>打开软件后，先确认摄像头预览正常。</li>
        <li>选择录制类型：发货 / 退货。</li>
        <li>扫描或输入单号后，系统自动开始录制。</li>
        <li>再次扫描同一单号，结束当前录制。</li>
        <li>录制中扫描不同单号，系统会保存上一单，并开始录制新单。</li>
        <li>录制完成后，可在“视频查询”中查看、备注、删除、上传或查看详情。</li>
        </ol>
        """,
    ),
    (
        "扫码规则",
        """
        <h1>扫码录制规则</h1>
        <ol>
        <li>未录制时，扫描有效单号：开始录制。</li>
        <li>录制中，扫描同一单号：结束录制。</li>
        <li>录制中，扫描不同单号：结束上一单并开始新单。</li>
        <li>录制中，空扫码：结束当前录制。</li>
        <li>未录制时空扫码：提示请输入或扫描单号。</li>
        </ol>
        """,
    ),
    (
        "摄像头异常",
        """
        <h1>摄像头异常提示</h1>
        <ol>
        <li>软件会实时监测摄像头状态。</li>
        <li>如果 iVCam 或摄像头连接异常，预览区域会出现红色波纹提示。</li>
        <li>摄像头异常时，系统会阻止开始录制，并播报异常语音。</li>
        <li>录制中摄像头中断时，系统会停止当前录制并标记异常。</li>
        <li>如果使用 iVCam，请确保手机和电脑网络稳定。</li>
        </ol>
        """,
    ),
    (
        "视频查询",
        """
        <h1>视频查询</h1>
        <ol>
        <li>支持按单号、日期、类型、上传状态查询。</li>
        <li>视频存储目录是录制保存和视频查询共用的全局目录，可在“设置 → 基础配置”中修改。</li>
        <li>支持分页查看。</li>
        <li>双击记录可查看单号详情。</li>
        <li>大小/时长列中，时长过短会用红色提示。</li>
        <li>文件状态列会显示正常、异常、文件不存在、重复录制和上传状态。</li>
        </ol>
        """,
    ),
    (
        "重复记录",
        """
        <h1>重复单号记录</h1>
        <ol>
        <li>点击“重复第 N 次”标签，可查看该单号所有录制记录。</li>
        <li>可打开视频预览。</li>
        <li>可单条删除或批量删除。</li>
        <li>删除前会二次确认。</li>
        <li>如果记录被标记为重要，删除时会额外提醒。</li>
        </ol>
        """,
    ),
    (
        "备注重要",
        """
        <h1>备注与重要标记</h1>
        <ol>
        <li>点击备注列可添加或编辑备注。</li>
        <li>在备注弹窗中可勾选“标记为重要”。</li>
        <li>重要原因支持售后争议、商家自行拦截、平台拦截退回、用户拒收和其他。</li>
        <li>选择“其他”时可填写补充原因。</li>
        <li>已标记为重要的记录删除时会额外提醒，防止误删。</li>
        </ol>
        """,
    ),
    (
        "统计",
        """
        <h1>打包发货统计</h1>
        <ol>
        <li>点击右上角统计按钮，可查看打包发货统计。</li>
        <li>所有统计均按录制时间 recorded_at 计算。</li>
        <li>统计页展示发货单数、退货单数和重要单数，三项数据均按单号去重。</li>
        <li>双击数据卡片可查看对应视频明细，明细页顶部会同时显示单号数量和视频记录数量。</li>
        <li>明细页支持双击单号复制，也支持打开和定位视频。</li>
        <li>明细页为只读列表，不支持删除或修改。</li>
        <li>统计支持今天、昨天、最近7天、本月、全部和自定义日期。</li>
        <li>对比分析支持今天 vs 昨天、本月 vs 上月、自定义区间对比。</li>
        </ol>
        """,
    ),
    (
        "网盘同步",
        """
        <h1>网盘同步</h1>
        <ol>
        <li>开启网盘同步后，可将未上传视频同步至百度网盘。</li>
        <li>支持上传失败重试。</li>
        <li>支持查看同步记录。</li>
        <li>同步记录中可查看上传时间、单号、状态、失败原因、远程路径和重试次数。</li>
        <li>上传失败的记录会保留失败原因，方便排查。</li>
        <li>开启自动同步后，系统会在最后一次录制结束并持续空闲指定时间后，自动上传未上传视频。</li>
        <li>倒计时期间再次录制会重新计时；同步过程中再次开始录制，系统会在当前文件完成后暂停，待录制结束并重新倒计时后继续。</li>
        <li>点击“停止同步”可取消倒计时或安全停止当前同步任务。</li>
        <li>自动同步只处理“未上传”记录，不自动重试“上传失败”记录。</li>
        </ol>
        """,
    ),
    (
        "配置迁移",
        """
        <h1>配置导出 / 导入</h1>
        <ol>
        <li>可导出配置为一个 zip 文件。</li>
        <li>可导入配置，方便换电脑或重装软件。</li>
        <li>导出配置包含视频存储目录、基础配置、语音配置、网盘基础配置等。</li>
        <li>出于安全考虑，不导出网盘 Secret 和授权 Token，导入后需要重新授权。</li>
        </ol>
        """,
    ),
    (
        "哈希校验",
        """
        <h1>视频哈希校验</h1>
        <ol>
        <li>新录制视频会生成 SHA256 哈希。</li>
        <li>哈希用于证明视频文件后续没有被修改。</li>
        <li>在单号详情中可查看哈希并进行校验。</li>
        <li>如果文件被修改，校验会提示不一致。</li>
        </ol>
        """,
    ),
    (
        "常见问题",
        """
        <h1>常见问题</h1>
        <p class="question">问题 1：摄像头提示异常怎么办？</p>
        <p>请检查 iVCam 是否连接、手机是否在线、网络是否稳定，或点击刷新摄像头。</p>

        <p class="question">问题 2：视频显示文件不存在怎么办？</p>
        <p>说明本地视频文件可能被移动或删除，可从列表中移除该记录。</p>

        <p class="question">问题 3：上传失败怎么办？</p>
        <p>可在“同步记录”中点击“重试上传失败”，并查看具体失败原因。</p>

        <p class="question">问题 4：为什么有重复第 N 次？</p>
        <p>表示同一单号存在多条录制记录，可点击标签查看并清理。</p>
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
