from __future__ import annotations

import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.theme.theme_tokens import LIGHT_TOKENS
from app.utils.runtime_paths import resource_path


_COLOR_ATTRIBUTE = re.compile(r'(?P<name>stroke|fill)="(?!none\b)[^"]+"', re.IGNORECASE)


def themed_svg_icon(icon_name: str, theme_manager=None, size: int = 24) -> QIcon:
    """Render one SVG into normal, hover and disabled theme-aware icon modes."""
    path = resource_path(f"app/assets/icons/{icon_name}.svg")
    if not path.exists():
        return QIcon()
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return QIcon()

    tokens = theme_manager.current_tokens() if theme_manager is not None else LIGHT_TOKENS
    icon = QIcon()
    for mode, color in (
        (QIcon.Normal, tokens.text_secondary),
        (QIcon.Active, tokens.text_primary),
        (QIcon.Selected, tokens.text_primary),
        (QIcon.Disabled, tokens.text_disabled),
    ):
        rendered = _render_svg(source, color, size)
        if not rendered.isNull():
            icon.addPixmap(rendered, mode, QIcon.Off)
    return icon


def _render_svg(source: str, color: str, size: int) -> QPixmap:
    themed_source = _COLOR_ATTRIBUTE.sub(lambda match: f'{match.group("name")}="{color}"', source)
    renderer = QSvgRenderer(themed_source.encode("utf-8"))
    if not renderer.isValid():
        return QPixmap()
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
