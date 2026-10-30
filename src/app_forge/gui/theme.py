"""GUI design tokens (light/dark) and style-sheet builder. Pure Python, no Qt import."""
from __future__ import annotations

TOKENS = {
    "light": {"background": "#ffffff", "surface": "#f3f5f8", "text": "#1b1f24", "muted": "#4a5360",
              "primary": "#0b5cad", "on_primary": "#ffffff", "border": "#8b94a1", "focus": "#b34700",
              "danger": "#b00020", "selection": "#cfe3fb"},
    "dark": {"background": "#14181d", "surface": "#1d232b", "text": "#e8ecf1", "muted": "#aab4c0",
             "primary": "#6db3ff", "on_primary": "#0a1626", "border": "#7c8796", "focus": "#ffb066",
             "danger": "#ff6b81", "selection": "#27415f"},
}


def stylesheet(name: str) -> str:
    t = TOKENS[name]
    return (
        "QWidget { background: %(background)s; color: %(text)s; font-size: 13px; }\n"
        "QListWidget#nav { background: %(surface)s; border-right: 1px solid %(border)s; padding: 4px; }\n"
        "QListWidget#nav::item { padding: 8px 10px; }\n"
        "QListWidget#nav::item:selected { background: %(selection)s; color: %(text)s; }\n"
        "QPushButton { background: %(primary)s; color: %(on_primary)s; border: 1px solid %(border)s; padding: 6px 14px; }\n"
        "QPushButton:disabled { background: %(surface)s; color: %(muted)s; }\n"
        "QPushButton:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus, "
        "QPlainTextEdit:focus { border: 2px solid %(focus)s; }\n"
        "QLineEdit, QComboBox, QPlainTextEdit, QTableWidget { border: 1px solid %(border)s; background: %(surface)s; }\n"
        "QHeaderView::section { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px; }\n"
        "QLabel#muted { color: %(muted)s; }\n"
        "QLabel#title { font-size: 20px; font-weight: bold; }\n"
        "QLabel#error { color: %(danger)s; }\n"
    ) % t


PAIRS = [("text", "background"), ("text", "surface"), ("muted", "background"), ("on_primary", "primary"),
         ("focus", "background"), ("danger", "background")]


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        chans.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast_ratio(fg: str, bg: str) -> float:
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_theme(name: str, minimum: float = 4.5) -> list[dict]:
    t = TOKENS[name]
    return [{"foreground": f, "background": b, "ratio": round(contrast_ratio(t[f], t[b]), 2),
             "ok": contrast_ratio(t[f], t[b]) >= minimum} for f, b in PAIRS]
