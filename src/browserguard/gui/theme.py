"""Colours and stylesheet for the window."""

from __future__ import annotations

COLORS = {
    "bg": "#12141a",
    "surface": "#1a1d26",
    "surface_alt": "#222630",
    "border": "#2e3340",
    "text": "#e8eaf0",
    "text_dim": "#9aa2b4",
    "accent": "#4f8cff",
    "accent_dim": "#3a6fd8",
    "good": "#3ecf8e",
    "warn": "#f5a623",
    "bad": "#ff5f56",
}

STYLESHEET = f"""
QWidget {{
    background: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QLabel#Title      {{ font-size: 22px; font-weight: 600; }}
QLabel#Subtitle   {{ color: {COLORS['text_dim']}; font-size: 13px; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; padding-top: 4px; }}
QLabel#Hint       {{ color: {COLORS['text_dim']}; font-size: 12px; }}
QLabel#StatusBig  {{ font-size: 26px; font-weight: 700; }}

/* ---- sidebar ---- */
QListWidget#Nav {{
    background: {COLORS['surface']};
    border: none;
    border-right: 1px solid {COLORS['border']};
    outline: none;
    padding-top: 12px;
}}
QListWidget#Nav::item {{
    padding: 11px 18px;
    margin: 2px 8px;
    border-radius: 8px;
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
    background: {COLORS['surface_alt']};
}}

/* ---- buttons ---- */
QPushButton {{
    background: {COLORS['surface_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 16px;
    color: {COLORS['text']};
}}
QPushButton:hover {{ background: {COLORS['border']}; }}
QPushButton:disabled {{ color: {COLORS['text_dim']}; background: {COLORS['surface']}; }}
QPushButton#Primary {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {COLORS['accent_dim']}; }}
QPushButton#Danger {{ color: {COLORS['bad']}; }}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: {COLORS['surface_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    padding: 7px 10px;
    selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {{
    border: 1px solid {COLORS['accent']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {COLORS['surface_alt']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent']};
}}

QListWidget, QTreeWidget, QTextEdit {{
    background: {COLORS['surface_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    outline: none;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {COLORS['accent']}; color: #fff; }}

QCheckBox {{ spacing: 9px; padding: 5px 0; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid {COLORS['border']};
    background: {COLORS['surface_alt']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
}}
QCheckBox::indicator:disabled {{ background: {COLORS['surface']}; }}

QHeaderView::section {{
    background: {COLORS['surface']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 8px;
    font-weight: 600;
}}
QTreeWidget::item {{ padding: 6px 4px; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea {{ border: none; }}

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
"""
