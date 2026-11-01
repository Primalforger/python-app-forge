import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
try:
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QLineEdit, QSpinBox
    HAVE_QT = True
except ImportError:
    HAVE_QT = False
from tests.helpers import ForgeTestCase

@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class SchemaSettingsDialogTests(ForgeTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_builds_controls_and_returns_typed_values(self):
        from app_forge.qt_settings import SchemaSettingsDialog
        dialog = SchemaSettingsDialog([
            {"key": "name", "label": "Project name", "type": "str", "default": "Demo"},
            {"key": "workers", "label": "Workers", "type": "int", "default": 4, "min": 1, "max": 12},
            {"key": "enabled", "label": "Enabled", "type": "bool", "default": True},
            {"key": "mode", "label": "Mode", "type": "choice", "choices": ["safe", "fast"], "default": "fast"},
        ])
        self.addCleanup(dialog.close)
        self.assertIsInstance(dialog.field_widgets["name"], QLineEdit)
        self.assertIsInstance(dialog.field_widgets["workers"], QSpinBox)
        self.assertIsInstance(dialog.field_widgets["enabled"], QCheckBox)
        self.assertIsInstance(dialog.field_widgets["mode"], QComboBox)
        self.assertEqual(dialog.values(), {"name": "Demo", "workers": 4, "enabled": True, "mode": "fast"})

    def test_invalid_required_value_prevents_acceptance(self):
        from app_forge.qt_settings import SchemaSettingsDialog
        dialog = SchemaSettingsDialog([{"key": "name", "label": "Name", "required": True}])
        self.addCleanup(dialog.close)
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIn("Name is required", dialog.error_label.text())

    def test_valid_form_accepts_and_numeric_bounds_are_enforced(self):
        from app_forge.qt_settings import SchemaSettingsDialog
        dialog = SchemaSettingsDialog([{"key": "limit", "label": "Limit", "type": "int", "default": 5, "min": 2, "max": 8}])
        self.addCleanup(dialog.close)
        dialog.field_widgets["limit"].setValue(7)
        self.assertEqual(dialog.validate(), [])
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_rejects_ambiguous_or_invalid_schemas(self):
        from app_forge.qt_settings import SchemaSettingsDialog
        with self.assertRaises(ValueError):
            SchemaSettingsDialog([{"key": "x"}, {"key": "x"}])
        with self.assertRaises(ValueError):
            SchemaSettingsDialog([{"key": "mode", "type": "choice", "choices": []}])
        with self.assertRaises(ValueError):
            SchemaSettingsDialog([{"key": "n", "type": "int", "min": 5, "max": 1}])

if __name__ == "__main__":
    unittest.main()
