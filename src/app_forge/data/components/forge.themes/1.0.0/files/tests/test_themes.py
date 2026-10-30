import unittest

from {{package}} import themes


class ThemeTests(unittest.TestCase):
    def test_all_themes_meet_wcag_aa_for_required_pairs(self):
        for name, tokens in themes.THEMES.items():
            self.assertEqual(themes.validate_theme(tokens), [], name)

    def test_contrast_extremes(self):
        self.assertAlmostEqual(themes.contrast_ratio("#000000", "#ffffff"), 21.0, places=1)

    def test_stylesheet_has_focus_outline(self):
        for name in themes.THEMES:
            self.assertIn("focus", themes.stylesheet(name))
