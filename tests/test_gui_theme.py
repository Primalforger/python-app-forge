"""Tests for the Forge Universe visual design tokens."""
import unittest

from app_forge.gui.theme import TOKENS, check_theme, stylesheet


class ForgeThemeTests(unittest.TestCase):
    def test_brand_palette_is_blue_dominant_with_green_and_purple_accents(self):
        for theme in TOKENS.values():
            self.assertEqual(theme["primary"], "#2563EB" if theme is TOKENS["light"] else "#3989E8")
            self.assertIn("success", theme)
            self.assertIn("accent", theme)
            self.assertNotEqual(theme["success"], theme["accent"])

    def test_core_text_and_status_colors_meet_contrast_target(self):
        for name in TOKENS:
            failures = [pair for pair in check_theme(name) if not pair["ok"]]
            self.assertEqual(failures, [], f"{name} theme has insufficient contrast")

    def test_stylesheet_has_consistent_controls_and_keyboard_focus(self):
        for name in TOKENS:
            sheet = stylesheet(name)
            self.assertIn("QPushButton:hover", sheet)
            self.assertIn("QTableWidget::item:selected", sheet)
            self.assertIn(":focus", sheet)
            self.assertIn("border-radius", sheet)

    def test_unknown_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            stylesheet("neon")


if __name__ == "__main__":
    unittest.main()
