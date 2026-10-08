"""通用 UI 组件与配色。"""

from __future__ import annotations

import html
from typing import Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# --------------------------------------------------------------------------- #
# 配色
# --------------------------------------------------------------------------- #

BG = "#0f1116"
SURFACE = "#171a21"
SURFACE_ALT = "#1e222b"
BORDER = "#2a2f3a"
BORDER_SOFT = "#232833"
TEXT = "#e7eaf0"
TEXT_DIM = "#98a2b3"
TEXT_FAINT = "#6b7480"
ACCENT = "#4f8cff"
ACCENT_DIM = "#2b4b87"
OK = "#3ecf8e"
WARN = "#f0b429"
ERR = "#f2555a"
INFO = "#6ea8fe"

LEVEL_COLORS = {
    "info": TEXT_DIM,
    "ok": OK,
    "warn": WARN,
    "error": ERR,
    "accent": INFO,
    "dim": TEXT_FAINT,
    "muted": TEXT_DIM,
}

CHIP_COLORS = {
    "ok": (OK, "#0d2b20"),
    "warn": (WARN, "#33260a"),
    "error": (ERR, "#331114"),
    "info": (INFO, "#101f38"),
    "muted": (TEXT_DIM, "#1c2029"),
}

PAGE_TITLES = {
    "dashboard": ("总览", "一眼看清当前语音参数、生效状态与风险项"),
    "params": ("参数方案", "编辑 audio_params.json —— 决定 inject 写入的目标音频参数"),
    "advanced": ("高级配置", "GME 控制配置解码、settings.json、hosts 屏蔽段"),
    "backups": ("备份与回滚", "查看 backups/ 中的原始文件，手动回滚被改写的配置"),
    "logs": ("日志与输出", "GMESDK 运行日志与每次操作的完整输出"),
    "help": ("帮助与说明", "命令对照、生效判定逻辑与风险提示"),
}


def mono_font(size: int = 10) -> QFont:
    font = QFont("Cascadia Mono")
    if not font.exactMatch():
        font = QFont("Consolas")
    if not font.exactMatch():
        font = QFont("Courier New")
    font.setPointSize(size)
    font.setStyleHint(QFont.Monospace)
    return font


# --------------------------------------------------------------------------- #
# 全局样式表
# --------------------------------------------------------------------------- #

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#Muted {{ color: {TEXT_DIM}; }}
QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 12px; }}
QLabel#MetricValue {{ font-size: 20px; font-weight: 700; }}
QLabel#MetricLabel {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#Mono {{ font-family: "Cascadia Mono", Consolas, "Courier New", monospace; color: {TEXT_DIM}; }}

QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#Inner {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
}}
QFrame#Divider {{ background: {BORDER_SOFT}; max-height: 1px; border: none; }}

QPushButton {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #262b36; border-color: #39404e; }}
QPushButton:pressed {{ background: #1a1e26; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: #171a21; border-color: {BORDER_SOFT}; }}
QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: #5f97ff; border-color: #5f97ff; }}
QPushButton#Primary:disabled {{ background: {ACCENT_DIM}; border-color: {ACCENT_DIM}; color: #c8d4ea; }}
QPushButton#Danger {{ border-color: #6b2a2e; color: #ff9a9d; }}
QPushButton#Danger:hover {{ background: #33161a; }}
QPushButton#Ghost {{ background: transparent; border-color: {BORDER_SOFT}; color: {TEXT_DIM}; }}
QPushButton#Ghost:hover {{ color: {TEXT}; border-color: #39404e; }}
QPushButton#Link {{ background: transparent; border: none; color: {INFO}; padding: 2px 4px; text-align: left; }}
QPushButton#Link:hover {{ text-decoration: underline; }}

QPushButton#Nav {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 9px 12px;
    color: {TEXT_DIM};
    text-align: left;
    font-size: 13px;
}}
QPushButton#Nav:hover {{ background: {SURFACE_ALT}; color: {TEXT}; }}
QPushButton#Nav:checked {{ background: {ACCENT_DIM}; color: #ffffff; font-weight: 600; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 9px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:read-only {{ color: {TEXT_DIM}; }}

QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    outline: none;
}}

QCheckBox {{ spacing: 8px; padding: 2px 0; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #333a47; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #414a5a; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #333a47; border-radius: 5px; min-width: 30px; }}

QTableWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: {BORDER_SOFT};
    selection-background-color: {ACCENT_DIM};
    selection-color: #ffffff;
}}
QTableWidget::item {{ padding: 5px 8px; border: none; }}
QHeaderView::section {{
    background: {SURFACE_ALT};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {SURFACE_ALT}; border: none; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {SURFACE}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 8px 16px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QTabBar::tab:selected {{ background: {SURFACE}; color: {TEXT}; border-color: {BORDER}; border-bottom-color: {SURFACE}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QProgressBar {{
    background: {SURFACE_ALT};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QToolTip {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 8px;
}}
"""


# --------------------------------------------------------------------------- #
# 基础组件
# --------------------------------------------------------------------------- #

class Card(QFrame):
    """带标题的内容卡片。"""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(16, 14, 16, 16)
        self._outer.setSpacing(10)

        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        self._outer.addLayout(self.header)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("Faint")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        self._outer.addWidget(self.subtitle_label)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self._outer.addLayout(self.body)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def add(self, widget: QWidget | QWidget) -> None:  # type: ignore[override]
        self.body.addWidget(widget)

    def add_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        self.body.addLayout(layout)

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)


class Chip(QLabel):
    """状态胶囊。"""

    def __init__(self, text: str = "", tone: str = "muted", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self._tone = tone
        self.set_tone(tone, text)

    def set_tone(self, tone: str, text: str | None = None) -> None:
        self._tone = tone
        fg, bg = CHIP_COLORS.get(tone, CHIP_COLORS["muted"])
        if text is not None:
            self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border: 1px solid {fg}44;"
            f" border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }}"
        )


class Metric(QFrame):
    """仪表盘上的小指标块。"""

    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inner")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.label_label = QLabel(label)
        self.label_label.setObjectName("MetricLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.label_label)

    def set_value(self, value: str, tone: str | None = None) -> None:
        self.value_label.setText(value)
        color = LEVEL_COLORS.get(tone or "", TEXT)
        self.value_label.setStyleSheet(f"color: {color};")


class KeyValue(QWidget):
    """左标签右值的行。"""

    def __init__(self, key: str, value: str = "—", mono: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(12)
        self.key_label = QLabel(key)
        self.key_label.setObjectName("Muted")
        self.key_label.setMinimumWidth(96)
        self.key_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.value_label = QLabel(value)
        self.value_label.setWordWrap(True)
        self.value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if mono:
            self.value_label.setObjectName("Mono")
        layout.addWidget(self.key_label, 0)
        layout.addWidget(self.value_label, 1)

    def set_value(self, value: str, tone: str | None = None) -> None:
        self.value_label.setText(value)
        if tone:
            self.value_label.setStyleSheet(f"color: {LEVEL_COLORS.get(tone, TEXT)};")
        else:
            self.value_label.setStyleSheet("")


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class LogView(QTextEdit):
    """只追加的彩色日志视图。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(mono_font(9))
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setUndoRedoEnabled(False)
        self.document().setMaximumBlockCount(4000)
        self.setPlaceholderText("操作输出会显示在这里 …")
        self.setMinimumHeight(160)

    def append(self, message: str, level: str = "info") -> None:
        color = LEVEL_COLORS.get(level, TEXT)
        safe = html.escape(str(message)).replace("\n", "<br>")
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self.document().characterCount() > 1:
            cursor.insertBlock()
        cursor.insertHtml(
            f'<span style="color:{color}; white-space:pre-wrap; text-indent:0">{safe}</span>'
        )
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def append_block(self, text: str, level: str = "info") -> None:
        for line in str(text).splitlines() or [""]:
            self.append(line, level)


class Section(QWidget):
    """滚动区域里的一个区块（标题 + 卡片）。"""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.card = Card(title, subtitle)
        layout.addWidget(self.card)


class ScrollPage(QWidget):
    """带内边距和滚动的页面基类。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)

        self.container = QWidget()
        self.content = QVBoxLayout(self.container)
        self.content.setContentsMargins(20, 18, 20, 24)
        self.content.setSpacing(14)
        self.scroll.setWidget(self.container)

        self.header = QVBoxLayout()
        self.header.setSpacing(2)
        self.content.addLayout(self.header)

    def add_page_title(self, title: str, subtitle: str = "") -> None:
        label = QLabel(title)
        label.setObjectName("PageTitle")
        self.header.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("PageSubtitle")
            sub.setWordWrap(True)
            self.header.addWidget(sub)

    def add(self, widget: QWidget) -> None:
        self.content.addWidget(widget)

    def add_stretch(self) -> None:
        self.content.addStretch(1)


def button_row(*widgets: QWidget, spacing: int = 8, stretch_at_end: bool = True) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch_at_end:
        layout.addStretch(1)
    return layout


def primary_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Primary")
    button.setCursor(Qt.PointingHandCursor)
    if on_click:
        button.clicked.connect(lambda: on_click())
    return button


def ghost_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Ghost")
    button.setCursor(Qt.PointingHandCursor)
    if on_click:
        button.clicked.connect(lambda: on_click())
    return button


def link_button(text: str, on_click: Callable[[], None] | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Link")
    button.setCursor(Qt.PointingHandCursor)
    if on_click:
        button.clicked.connect(lambda: on_click())
    return button


def table_columns(table, headers: Iterable[str]) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QHeaderView, QTableWidget

    assert isinstance(table, QTableWidget)
    names = list(headers)
    table.setColumnCount(len(names))
    table.setHorizontalHeaderLabels(names)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
