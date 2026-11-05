"""Forge Universe design tokens and accessible Qt stylesheet.

The visual system is intentionally restrained: electric blue is the primary
brand color, while green and purple are semantic accents rather than decoration.
This module stays independent of Qt so contrast and stylesheet behavior can be
tested in lightweight environments.
"""
from __future__ import annotations

TOKENS = {
    "light": {
        "background": "#F4F7FB",
        "surface": "#FFFFFF",
        "surface_alt": "#EAF0F8",
        "text": "#172033",
        "muted": "#536176",
        "primary": "#2563EB",
        "on_primary": "#FFFFFF",
        "border": "#C7D2E2",
        "focus": "#7C3AED",
        "danger": "#B42335",
        "success": "#087A55",
        "accent": "#6D42C7",
        "selection": "#DCE9FF",
        "hover": "#E8F0FE",
    },
    "dark": {
        "background": "#111827",
        "surface": "#192438",
        "surface_alt": "#202E45",
        "text": "#F1F5FB",
        "muted": "#B4C0D2",
        "primary": "#3989E8",
        "on_primary": "#0B1B30",
        "border": "#35445C",
        "focus": "#B69AF5",
        "danger": "#FF8794",
        "success": "#45C99A",
        "accent": "#A88AEF",
        "selection": "#243F68",
        "hover": "#253650",
    },
}


def stylesheet(name: str) -> str:
    """Return the shared application stylesheet for the requested theme."""
    if name not in TOKENS:
        raise ValueError(f"unknown theme: {name}")
    t = TOKENS[name]
    return (
        "QWidget {"
        " background: %(background)s; color: %(text)s;"
        " font-family: 'Segoe UI', 'Inter', 'Arial', sans-serif;"
        " font-size: 13px; }\n"
        "QMainWindow, QDialog { background: %(background)s; }\n"
        "QMenuBar, QMenu { background: %(surface)s; color: %(text)s;"
        " border: 1px solid %(border)s; padding: 4px; }\n"
        "QMenu::item { padding: 6px 24px; border-radius: 4px; }\n"
        "QMenu::item:selected { background: %(selection)s; color: %(text)s; }\n"
        "QListWidget#nav { background: %(surface)s; border: 1px solid %(border)s;"
        " border-radius: 10px; padding: 8px; outline: none; }\n"
        "QListWidget#nav::item { padding: 10px 12px; margin: 2px 0;"
        " border-radius: 6px; }\n"
        "QListWidget#nav::item:hover { background: %(hover)s; }\n"
        "QListWidget#nav::item:selected { background: %(selection)s;"
        " color: %(text)s; border-left: 3px solid %(primary)s; }\n"
        "QPushButton { background: %(primary)s; color: %(on_primary)s;"
        " border: 1px solid %(primary)s; border-radius: 6px;"
        " padding: 7px 14px; min-height: 18px; font-weight: 600; }\n"
        "QPushButton:hover { background: %(hover)s; color: %(text)s;"
        " border-color: %(primary)s; }\n"
        "QPushButton:pressed { background: %(selection)s; color: %(text)s; }\n"
        "QPushButton:disabled { background: %(surface_alt)s;"
        " color: %(muted)s; border-color: %(border)s; }\n"
        "QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {"
        " background: %(surface)s; color: %(text)s; border: 1px solid %(border)s;"
        " border-radius: 5px; padding: 6px; selection-background-color: %(selection)s;"
        " selection-color: %(text)s; }\n"
        "QComboBox::drop-down { border: 0; padding-right: 8px; }\n"
        "QTableWidget { gridline-color: %(border)s; alternate-background-color: %(surface_alt)s; }\n"
        "QTableWidget::item { padding: 5px; }\n"
        "QTableWidget::item:selected { background: %(selection)s; color: %(text)s; }\n"
        "QHeaderView::section { background: %(surface_alt)s; color: %(text)s;"
        " border: 0; border-bottom: 1px solid %(border)s; padding: 8px;"
        " font-weight: 600; }\n"
        "QLabel#muted { color: %(muted)s; }\n"
        "QLabel#eyebrow { color: %(primary)s; font-size: 10px; font-weight: 700; letter-spacing: 1px; }\n"
        "QLabel#metricCard { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; border-radius: 8px; padding: 10px 12px; font-size: 12px; }\n"
        "QLabel#metricCard b { color: %(primary)s; font-size: 19px; font-weight: 700; }\n"
        "QPushButton#secondaryAction { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; }\n"
        "QPushButton#secondaryAction:hover { background: %(hover)s; border-color: %(primary)s; }\n"
        "QLabel#title { color: %(text)s; font-size: 21px; font-weight: 700; padding-bottom: 4px; }\n"
        "QLabel#error { color: %(danger)s; }\n"
        "QToolTip { background: %(surface)s; color: %(text)s;"
        " border: 1px solid %(border)s; padding: 5px; }\n"
        "QPushButton:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus,"
        " QTableWidget:focus, QPlainTextEdit:focus { border: 2px solid %(focus)s; }\n"
    ) % t


PAIRS = [
    ("text", "background"),
    ("text", "surface"),
    ("muted", "background"),
    ("on_primary", "primary"),
    ("focus", "background"),
    ("danger", "background"),
    ("success", "background"),
]


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        chans.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast_ratio(fg: str, bg: str) -> float:
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_theme(name: str, minimum: float = 4.5) -> list[dict]:
    """Report WCAG-style contrast checks for core text and status pairs."""
    if name not in TOKENS:
        raise ValueError(f"unknown theme: {name}")
    t = TOKENS[name]
    return [
        {
            "foreground": foreground,
            "background": background,
            "ratio": round(contrast_ratio(t[foreground], t[background]), 2),
            "ok": contrast_ratio(t[foreground], t[background]) >= minimum,
        }
        for foreground, background in PAIRS
    ]
