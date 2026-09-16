"""Colours and stylesheet for the window."""

from __future__ import annotations

COLORS = {
    "bg": "#f4f6fa",
    "surface": "#ffffff",
    "surface_alt": "#eef1f7",
    "border": "#d7dce7",
    "border_soft": "#e6eaf2",
    "text": "#1b2030",
    "text_dim": "#616a80",
    "accent": "#2f6fed",
    "accent_dim": "#2358c9",
    "accent_soft": "#e8f0ff",
    "good": "#128a5a",
    "good_soft": "#e4f6ee",
    "warn": "#b06f00",
    "warn_soft": "#fdf3e2",
    "bad": "#c8372d",
    "bad_soft": "#fdecea",
}

STYLESHEET = f"""
QWidget {{
    background: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: 'Segoe UI', -apple-system, sans-serif;
    font-size: 14px;
}}

QLabel#Title       {{ font-size: 23px; font-weight: 700; }}
QLabel#Subtitle    {{ color: {COLORS['text_dim']}; font-size: 13px; }}
QLabel#SectionTitle{{ font-size: 15px; font-weight: 700; }}
QLabel#Hint        {{ color: {COLORS['text_dim']}; font-size: 12px; }}
QLabel#StatusBig   {{ font-size: 27px; font-weight: 700; }}
QLabel#WizardTitle {{ font-size: 25px; font-weight: 700; }}
QLabel#WizardStep  {{ color: {COLORS['text_dim']}; font-size: 12px; font-weight: 600; }}

/* ---- sidebar ---- */
QListWidget#Nav {{
    background: {COLORS['surface']};
    border: none;
    border-right: 1px solid {COLORS['border']};
    outline: none;
    padding-top: 14px;
}}
QListWidget#Nav::item {{
    padding: 12px 18px;
    margin: 3px 10px;
    border-radius: 9px;
    color: {COLORS['text_dim']};
}}
QListWidget#Nav::item:selected {{
    background: {COLORS['accent']};
    color: #ffffff;
    font-weight: 600;
}}
QListWidget#Nav::item:hover:!selected {{ background: {COLORS['surface_alt']}; }}

/* ---- cards ---- */
QFrame#Card {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
}}
QFrame#Banner {{
    border-radius: 10px;
    border: 1px solid {COLORS['border']};
    background: {COLORS['surface']};
}}
QFrame#Choice {{
    background: {COLORS['surface']};
    border: 2px solid {COLORS['border']};
    border-radius: 11px;
}}
QFrame#ChoiceSelected {{
    background: {COLORS['accent_soft']};
    border: 2px solid {COLORS['accent']};
    border-radius: 11px;
}}

/* ---- buttons ---- */
QPushButton {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 9px 18px;
    color: {COLORS['text']};
}}
QPushButton:hover {{ background: {COLORS['surface_alt']}; }}
QPushButton:disabled {{ color: #a7aebf; background: {COLORS['surface_alt']}; }}
QPushButton#Primary {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {COLORS['accent_dim']}; }}
QPushButton#Primary:disabled {{ background: #a8c0f4; border-color: #a8c0f4; color: #ffffff; }}
QPushButton#Danger {{ color: {COLORS['bad']}; border-color: #eec4c0; }}
QPushButton#Danger:hover {{ background: {COLORS['bad_soft']}; }}
QPushButton#Link {{
    border: none;
    background: transparent;
    color: {COLORS['accent']};
    padding: 4px 6px;
    text-decoration: underline;
}}
QPushButton#Link:hover {{ background: transparent; color: {COLORS['accent_dim']}; }}
QPushButton#Chip {{
    padding: 7px 14px;
    border-radius: 16px;
    color: {COLORS['text_dim']};
}}
QPushButton#ChipOn {{
    padding: 7px 14px;
    border-radius: 16px;
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    color: #ffffff;
    font-weight: 600;
}}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 9px 11px;
    selection-background-color: {COLORS['accent']};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {{
    border: 1px solid {COLORS['accent']};
}}
QLineEdit::placeholder {{ color: #9aa2b4; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent']};
    selection-color: #ffffff;
    outline: none;
}}

QListWidget, QTreeWidget, QTextEdit {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 9px;
    outline: none;
}}
QListWidget::item {{ padding: 8px 9px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {COLORS['accent_soft']}; color: {COLORS['text']}; }}
QListWidget::item:hover:!selected {{ background: {COLORS['surface_alt']}; }}

QCheckBox {{ spacing: 10px; padding: 3px 0; }}
QCheckBox::indicator {{
    width: 19px; height: 19px;
    border-radius: 5px;
    border: 1px solid #bcc4d4;
    background: {COLORS['surface']};
}}
QCheckBox::indicator:hover {{ border: 1px solid {COLORS['accent']}; }}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    image: none;
}}
QCheckBox::indicator:disabled {{ background: {COLORS['surface_alt']}; border-color: {COLORS['border']}; }}

QRadioButton {{ spacing: 10px; padding: 3px 0; }}
QRadioButton::indicator {{
    width: 18px; height: 18px;
    border-radius: 9px;
    border: 1px solid #bcc4d4;
    background: {COLORS['surface']};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {COLORS['accent']};
    background: {COLORS['surface']};
}}

QHeaderView::section {{
    background: {COLORS['surface_alt']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 9px;
    font-weight: 600;
    color: {COLORS['text_dim']};
}}
QTreeWidget::item {{ padding: 6px 4px; }}
QTreeWidget::item:selected {{ background: {COLORS['accent_soft']}; color: {COLORS['text']}; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #c4cbd9; border-radius: 5px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #aab3c5; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}

QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {COLORS['text_dim']};
    font-weight: 600;
}}

QToolTip {{
    background: #2b3242;
    color: #ffffff;
    border: none;
    padding: 7px 9px;
    border-radius: 6px;
}}

QDialog {{ background: {COLORS['bg']}; }}
QMessageBox {{ background: {COLORS['surface']}; }}
"""
