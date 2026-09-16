"""Small reusable pieces of the interface."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from browserguard.gui.theme import COLORS


class Card(QFrame):
    """A titled panel."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            self._layout.addWidget(label)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            self._layout.addWidget(hint)

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    def body(self) -> QVBoxLayout:
        return self._layout


class Banner(QFrame):
    """A coloured strip for status, warnings and pending changes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 11, 14, 11)
        self._layout.setSpacing(12)

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout.addWidget(self.label, 1)

        self.buttons: list[QPushButton] = []
        self.hide()

    def show_message(self, text: str, tone: str = "info") -> None:
        border = {
            "info": COLORS["accent"],
            "good": COLORS["good"],
            "warn": COLORS["warn"],
            "bad": COLORS["bad"],
        }.get(tone, COLORS["accent"])
        self.setStyleSheet(
            f"QFrame#Banner {{ border: 1px solid {border};"
            f" background: {COLORS['surface_alt']}; border-radius: 10px; }}"
        )
        self.label.setText(text)
        self.show()

    def add_button(self, text: str, on_click, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("Primary")
        button.clicked.connect(on_click)
        self._layout.addWidget(button)
        self.buttons.append(button)
        return button

    def clear_buttons(self) -> None:
        for button in self.buttons:
            self._layout.removeWidget(button)
            button.deleteLater()
        self.buttons.clear()


class PageHeader(QWidget):
    """Title and one-line description at the top of a page."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(3)
        heading = QLabel(title)
        heading.setObjectName("Title")
        layout.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Subtitle")
            sub.setWordWrap(True)
            layout.addWidget(sub)


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color: {COLORS['border']}; background: {COLORS['border']};")
    line.setFixedHeight(1)
    return line


def row(*widgets: QWidget, stretch_last: bool = False, spacing: int = 8) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        is_last = index == len(widgets) - 1
        layout.addWidget(widget, 1 if (stretch_last and is_last) else 0)
    return layout


def dim(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


def colored(text: str, color: str, size: int = 13, bold: bool = True) -> QLabel:
    label = QLabel(text)
    weight = "600" if bold else "400"
    label.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {weight};")
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label
