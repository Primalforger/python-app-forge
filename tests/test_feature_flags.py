import threading
import unittest

from app_forge.feature_flags import FeatureFlags


class FeatureFlagsTests(unittest.TestCase):
    def test_defaults_and_runtime_overrides(self):
        flags = FeatureFlags({"new-ui": False, "safe-mode": True})
        self.assertFalse(flags.is_enabled("new-ui"))
        self.assertTrue(flags.is_enabled("safe-mode"))
        flags.set_override("new-ui", True)
        self.assertTrue(flags.is_enabled("new-ui"))
        self.assertEqual(flags.defaults(), {"new-ui": False, "safe-mode": True})
        self.assertEqual(flags.snapshot(), {"new-ui": True, "safe-mode": True})
        self.assertTrue(flags.clear_override("new-ui"))
        self.assertFalse(flags.is_enabled("new-ui"))
        self.assertFalse(flags.clear_override("new-ui"))
        flags.set_override("safe-mode", False)
        self.assertTrue(flags.clear_override("safe-mode"))
        self.assertTrue(flags.is_enabled("safe-mode"))

    def test_register_and_duplicate_rejection(self):
        flags = FeatureFlags()
        flags.register("reports.v2", True)
        self.assertTrue(flags.is_enabled("reports.v2"))
        with self.assertRaises(ValueError):
            flags.register("reports.v2", False)

    def test_unknown_flags_fail_closed(self):
        flags = FeatureFlags()
        with self.assertRaises(KeyError):
            flags.is_enabled("missing")
        with self.assertRaises(KeyError):
            flags.set_override("missing", True)
        with self.assertRaises(KeyError):
            flags.clear_override("missing")

    def test_names_and_values_are_validated(self):
        for name in ("", "Upper", "1flag", "flag name", "a/" + "b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                FeatureFlags({name: True})
        for value in (1, 0, "true", None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                FeatureFlags({"flag": value})  # type: ignore[dict-item]
        with self.assertRaises(TypeError):
            FeatureFlags([])  # type: ignore[arg-type]

    def test_returned_mappings_are_independent_copies(self):
        flags = FeatureFlags({"alpha": True})
        defaults = flags.defaults()
        snapshot = flags.snapshot()
        defaults["alpha"] = False
        snapshot["alpha"] = False
        self.assertTrue(flags.is_enabled("alpha"))

    def test_concurrent_override_and_snapshot(self):
        flags = FeatureFlags({"enabled": False})
        failures = []

        def writer():
            try:
                for index in range(500):
                    flags.set_override("enabled", bool(index % 2))
                    flags.snapshot()
            except Exception as error:  # pragma: no cover - diagnostic path
                failures.append(error)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        self.assertIsInstance(flags.is_enabled("enabled"), bool)


if __name__ == "__main__":
    unittest.main()
