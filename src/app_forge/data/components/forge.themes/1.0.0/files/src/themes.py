"""Light/dark theme tokens with WCAG contrast validation and a Qt style-sheet generator.

Pure Python: usable (and testable) without any GUI toolkit installed.
"""
from __future__ import annotations

LIGHT = {"background": "#ffffff", "surface": "#f3f5f8", "text": "#1b1f24", "text_muted": "#4a5360",
         "primary": "#0b5cad", "on_primary": "#ffffff", "border": "#8b94a1", "focus": "#b34700",
         "danger": "#b00020"}
DARK = {"background": "#14181d", "surface": "#1d232b", "text": "#e8ecf1", "text_muted": "#aab4c0",
        "primary": "#6db3ff", "on_primary": "#0a1626", "border": "#7c8796", "focus": "#ffb066",
        "danger": "#ff6b81"}
THEMES = {"light": LIGHT, "dark": DARK}

# (foreground token, background token) pairs that must meet the minimum contrast ratio.
REQUIRED_PAIRS = [("text", "background"), ("text", "surface"), ("text_muted", "background"),
                  ("on_primary", "primary"), ("focus", "background")]


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def validate_theme(tokens: dict, minimum: float = 4.5) -> list[str]:
    """Return human-readable contrast failures (empty list means the theme passes)."""
    problems = []
    for fg, bg in REQUIRED_PAIRS:
        ratio = contrast_ratio(tokens[fg], tokens[bg])
        if ratio < minimum:
            problems.append(f"{fg} on {bg}: {ratio:.2f} < {minimum}")
    return problems


def stylesheet(name: str) -> str:
    """Build a Qt style sheet from theme tokens. Focus is always visibly outlined."""
    t = THEMES[name]
    return (
        "QWidget { background: %(background)s; color: %(text)s; }\n"
        "QFrame#sidebar, QListWidget#sidebar { background: %(surface)s; border-right: 1px solid %(border)s; }\n"
        "QPushButton { background: %(primary)s; color: %(on_primary)s; border: 1px solid %(border)s; padding: 6px 12px; }\n"
        "QPushButton:focus, QLineEdit:focus, QListWidget:focus, QTableView:focus { outline: 2px solid %(focus)s; "
        "border: 2px solid %(focus)s; }\n"
        "QLabel#muted { color: %(text_muted)s; }\n"
        "QLabel#error { color: %(danger)s; }\n"
    ) % t
