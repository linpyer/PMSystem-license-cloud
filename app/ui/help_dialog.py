from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout

from app.utils.runtime_paths import resource_path


HELP_STYLE = """
body {
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    color: #1f2937;
    line-height: 1.72;
    font-size: 14px;
    margin: 0;
}
h1 {
    font-size: 20px;
    margin: 4px 0 14px 0;
    color: #0f172a;
}
h2 {
    font-size: 16px;
    margin: 18px 0 8px 0;
    color: #0f766e;
}
ol {
    margin: 0 0 0 22px;
    padding: 0;
}
li {
    margin: 5px 0;
}
p {
    margin: 7px 0;
}
.question {
    font-weight: 700;
    color: #111827;
    margin-top: 13px;
}
.note {
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 6px;
    padding: 8px 10px;
    color: #78350f;
    margin-top: 8px;
}
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
        <li>在备注弹窗中可勾选“标记为重要视频”。</li>
        <li>重要视频适合用于售后争议、客户反馈、待核实等场景。</li>
        <li>重要视频删除时会额外提醒，防止误删。</li>
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
        <li>导出配置包含保存目录、基础配置、语音配置、网盘基础配置等。</li>
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
        <p>可点击“重试上传失败”，或查看“同步记录”中的失败原因。</p>

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
        self.resize(760, 580)
        self.setMinimumSize(660, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("helpTabs")
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setObjectName("helpTabBar")
        for title, html in HELP_TABS:
            self.tabs.addTab(self._create_tab(html), title)
        layout.addWidget(self.tabs, 1)
        QTimer.singleShot(0, self._style_tab_scroll_buttons)

    def _create_tab(self, html: str) -> QTextBrowser:
        browser = QTextBrowser(self)
        browser.setObjectName("helpContent")
        browser.setOpenExternalLinks(False)
        browser.setHtml(f'<!doctype html><html><head><meta charset="utf-8"><style>{HELP_STYLE}</style></head><body>{html}</body></html>')
        return browser

    def _style_tab_scroll_buttons(self) -> None:
        left_icon = QIcon(str(resource_path("app/assets/icons/chevron-left.svg")))
        right_icon = QIcon(str(resource_path("app/assets/icons/chevron-right.svg")))
        for button in self.tabs.findChildren(QToolButton):
            arrow = button.arrowType()
            if arrow == Qt.LeftArrow:
                button.setObjectName("helpPrevButton")
                button.setArrowType(Qt.NoArrow)
                button.setIcon(left_icon)
            elif arrow == Qt.RightArrow:
                button.setObjectName("helpNextButton")
                button.setArrowType(Qt.NoArrow)
                button.setIcon(right_icon)
            elif button.objectName() not in {"helpPrevButton", "helpNextButton"}:
                continue
            button.setFixedSize(36, 36)
            button.setIconSize(QSize(16, 16))
            button.setCursor(Qt.PointingHandCursor)
            button.style().unpolish(button)
            button.style().polish(button)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._style_tab_scroll_buttons)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QTimer.singleShot(0, self._style_tab_scroll_buttons)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)
