import tempfile
import unittest
from pathlib import Path

from {{package}}.settings import load_settings


class SettingsTests(unittest.TestCase):
    def _cfg(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "c.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_profile_overrides_default_and_env_overrides_profile(self):
        p = self._cfg('[default]\nmode="a"\nlevel=1\n[prod]\nmode="b"\n')
        s = load_settings(p, "prod", environ={"APP_LEVEL": "9"})
        self.assertEqual((s.get("mode"), s.get("level")), ("b", "9"))

    def test_secrets_only_from_env_and_redacted(self):
        p = self._cfg('[default]\nmode="a"\n')
        s = load_settings(p, secret_names=("db_password",), environ={"APP_DB_PASSWORD": "x"})
        self.assertEqual(s.secret("db_password"), "x")
        self.assertEqual(s.redacted()["secrets"]["db_password"], "[REDACTED]")

    def test_secret_in_file_is_rejected(self):
        p = self._cfg('[default]\ndb_password="oops"\n')
        with self.assertRaises(ValueError):
            load_settings(p, secret_names=("db_password",), environ={})
