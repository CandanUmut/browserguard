"""Small reusable pieces of the interface."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
        self._layout.setContentsMargins(18, 15, 18, 15)
        self._layout.setSpacing(9)
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


class ChoiceCard(QFrame):
    """A large clickable option, used for protection levels and waiting periods."""

    clicked = Signal()

    def __init__(self, title: str, description: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Choice")
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(5)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        layout.addWidget(self.title_label)

        self.description_label = QLabel(description)
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self.description_label)
        layout.addStretch(1)

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.setObjectName("ChoiceSelected" if selected else "Choice")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class Banner(QFrame):
    """A coloured strip for status, warnings and pending changes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 11, 14, 11)
        self._layout.setSpacing(10)

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.label.setStyleSheet("background: transparent;")
        self._layout.addWidget(self.label, 1)

        self.buttons: list[QPushButton] = []
        self.hide()

    def show_message(self, text: str, tone: str = "info") -> None:
        border, background = {
            "info": (COLORS["accent"], COLORS["accent_soft"]),
            "good": (COLORS["good"], COLORS["good_soft"]),
            "warn": (COLORS["warn"], COLORS["warn_soft"]),
            "bad": (COLORS["bad"], COLORS["bad_soft"]),
        }.get(tone, (COLORS["accent"], COLORS["accent_soft"]))
        self.setStyleSheet(
            f"QFrame#Banner {{ border: 1px solid {border}; background: {background};"
            " border-radius: 10px; }"
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
        layout.setContentsMargins(0, 0, 0, 2)
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
    line.setStyleSheet(
        f"color: {COLORS['border_soft']}; background: {COLORS['border_soft']}; border: none;"
    )
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


def colored(text: str, color: str, size: int = 14, bold: bool = True) -> QLabel:
    label = QLabel(text)
    weight = "700" if bold else "400"
    label.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent;"
    )
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def primary(text: str, on_click=None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Primary")
    button.setMinimumHeight(38)
    if on_click is not None:
        button.clicked.connect(on_click)
    return button


def link(text: str, on_click=None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Link")
    button.setCursor(Qt.PointingHandCursor)
    if on_click is not None:
        button.clicked.connect(on_click)
    return button
