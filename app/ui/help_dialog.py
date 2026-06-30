from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout


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
        "打包录制",
        """
        <h1>打包录制说明</h1>
        <ol>
        <li>打开软件后，进入“打包监控”页面。</li>
        <li>确认摄像头画面正常显示。</li>
        <li>使用扫码枪扫描物流单号后，系统会自动开始录制。</li>
        <li>录制中，视频画面会写入物流单号和当前日期时间水印。</li>
        <li>录制中预览画面会实时显示物流单号和当前日期时间，方便确认最终视频效果。</li>
        <li>再次扫描新的物流单号时，系统会自动结束上一个视频，并立即开始新单号的视频录制。</li>
        <li>如果当前正在录制某个单号，再次扫描同一个单号，系统会认为该订单打包完成，并结束当前录制；此时只保存当前视频，不会开启新的录制。</li>
        <li>如果扫码结果为空，系统会结束当前录制，但不会开始新录制。</li>
        <li>如果单号已有历史录制记录，系统会给出重复录制提示，但不会阻止继续录制。</li>
        <li>打包监控页右侧会显示最近保存成功的视频记录，可以快速打开视频或定位文件。</li>
        <li>录制过程中请尽量不要关闭软件。</li>
        <li>如果关闭软件时正在录制，系统会提示是否结束并保存当前视频。</li>
        </ol>
        """,
    ),
    (
        "视频查询",
        """
        <h1>视频查询说明</h1>
        <ol>
        <li>进入“视频查询”页面后，可以查看当前查询目录下的所有打包视频。</li>
        <li>可以在搜索框输入物流单号或视频名称进行搜索。</li>
        <li>可以通过“今天”“昨天”“最近 7 天”“全部”等按钮快速筛选视频。</li>
        <li>也可以通过开始日期和结束日期筛选指定时间范围内的视频。</li>
        <li>点击视频名称可以调用 Windows 默认播放器打开视频。</li>
        <li>双击视频列表中的视频行，也可以打开对应视频。</li>
        <li>如果视频较多，系统会使用本地 SQLite 数据库 pm_system.db 保存视频索引并提升查询速度。</li>
        <li>列表底部支持分页，可以选择每页 10、20、50 或 100 条，并支持上一页、下一页、页码按钮和指定页跳转。</li>
        <li>搜索、日期筛选和发货/退货类型筛选会自动刷新分页，并回到第 1 页。</li>
        <li>如果同一个物流单号存在多条视频记录，文件状态列会显示“正常”和“重复第 N 次”标签。</li>
        </ol>
        """,
    ),
    (
        "查询目录",
        """
        <h1>查询目录说明</h1>
        <ol>
        <li>视频查询页面顶部会显示当前查询目录。</li>
        <li>可以直接在“当前查询目录”输入框中输入本地文件夹路径。</li>
        <li>输入路径后按 Enter 回车，即可切换查询目录并刷新视频列表。</li>
        <li>也可以点击“选择目录”按钮，通过系统窗口选择视频文件夹。</li>
        <li>点击“恢复默认”可以恢复到软件配置中的默认视频保存目录。</li>
        <li>切换查询目录只影响视频查询页面，不会修改打包录制的视频保存目录。</li>
        <li>查询结果来自本地 SQLite 数据库；切换查询目录后，刷新列表会扫描当前目录并更新数据库索引。</li>
        <li>第一版默认只查询当前目录下的视频，不扫描子文件夹。</li>
        </ol>
        """,
    ),
    (
        "删除视频",
        """
        <h1>删除视频说明</h1>
        <ol>
        <li>视频查询列表中可以通过“删除”按钮删除对应视频。</li>
        <li>删除前系统会弹出确认窗口。</li>
        <li>点击“确认”后执行删除。</li>
        <li>点击“取消”则不会删除。</li>
        <li>删除成功后，系统会通过悬浮 Toast 提示“删除成功”。</li>
        <li>删除失败时，系统会通过悬浮 Toast 显示失败原因。</li>
        <li>删除视频属于敏感操作，请确认不再需要该视频后再删除。</li>
        <li>当前版本采用直接删除方式，删除后可能无法恢复，请谨慎操作。</li>
        <li>删除视频后，查询页会重新计算重复录制次数。</li>
        </ol>
        """,
    ),
    (
        "基础配置",
        """
        <h1>基础配置说明</h1>
        <ol>
        <li>基础配置位于右上角“设置”入口中的“基础配置”页签。</li>
        <li>摄像头设备：用于选择当前软件录制使用的摄像头。</li>
        <li>分辨率：用于设置摄像头采集画面的清晰度。</li>
        <li>帧率：用于设置每秒录制多少张画面，推荐使用 25 FPS。</li>
        <li>录制长边上限：用于限制录制视频最大分辨率，推荐使用 1280。</li>
        <li>水印字号：用于设置视频中物流单号和日期时间水印的文字大小。</li>
        <li>水印边距：用于设置水印文字距离视频边缘的距离。</li>
        <li>如果不确定如何设置，建议保持默认配置。</li>
        <li>修改基础配置后，请点击保存并应用配置，并重新确认摄像头画面和录制效果。</li>
        <li>正在录制时不建议修改基础配置，请结束录制后再调整。</li>
        </ol>
        """,
    ),
    (
        "数据保存",
        """
        <h1>数据保存说明</h1>
        <ol>
        <li>视频文件默认保存在软件配置的视频保存目录中。</li>
        <li>查询页面可以临时切换查询目录，但不会影响录制保存目录。</li>
        <li>日志文件用于记录软件运行状态和异常信息，方便排查问题。</li>
        <li>卸载软件不会自动删除已经录制的视频。</li>
        <li>请定期检查硬盘剩余空间，避免空间不足导致录制失败。</li>
        <li>建议定期将重要视频备份到移动硬盘或其他安全位置。</li>
        <li>不建议随意移动正在录制中的视频文件。</li>
        <li>pm_system.db 保存视频索引、备注、发货/退货类型和重复录制序号；完整备份时建议同时备份视频目录、pm_system.db 和 config.json。</li>
        </ol>
        """,
    ),
    (
        "常见问题",
        """
        <h1>常见问题</h1>
        <p class="question">问题 1：扫码后没有开始录制怎么办？</p>
        <p>请确认扫码枪是否能在输入框中正常输入单号，并确认扫码后是否自动回车。如果扫码枪没有自动回车，需要调整扫码枪设置或手动按 Enter。</p>

        <p class="question">问题 2：摄像头画面打不开怎么办？</p>
        <p>请检查摄像头是否连接正常，是否被其他软件占用。可以尝试关闭其他占用摄像头的软件，或重新插拔摄像头。</p>

        <p class="question">问题 3：视频查不到怎么办？</p>
        <p>请确认当前查询目录是否正确。可以在视频查询页面查看“当前查询目录”，也可以点击“恢复默认”回到默认视频保存目录。</p>

        <p class="question">问题 4：视频文件很大怎么办？</p>
        <p>可以适当降低分辨率、帧率或录制长边上限。一般推荐帧率 25 FPS，录制长边上限 1280。</p>

        <p class="question">问题 5：提示硬盘空间不足怎么办？</p>
        <p>请及时转移或备份旧视频，释放硬盘空间。系统不会自动删除视频，避免误删证据。</p>

        <p class="question">问题 6：卸载软件后视频还在吗？</p>
        <p>默认情况下，卸载软件不会自动删除已经录制的视频。视频仍保留在原来的视频保存目录中。</p>
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
        for title, html in HELP_TABS:
            self.tabs.addTab(self._create_tab(html), title)
        layout.addWidget(self.tabs, 1)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.close_button = QPushButton("关闭", self)
        self.close_button.setFixedWidth(96)
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)

    def _create_tab(self, html: str) -> QTextBrowser:
        browser = QTextBrowser(self)
        browser.setObjectName("helpContent")
        browser.setOpenExternalLinks(False)
        browser.setHtml(f'<!doctype html><html><head><meta charset="utf-8"><style>{HELP_STYLE}</style></head><body>{html}</body></html>')
        return browser

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)
