import json
import os
import unittest
from datetime import datetime, timezone

from app_forge.settings import ForgeSettings
from tests.helpers import ForgeTestCase


class HousekeepingTests(ForgeTestCase):
    def test_gc_dry_run_reports_expired_data_without_deleting(self):
        s = self.services()
        s.settings.plan_retention_days = 10
        s.settings.checkpoint_retention_days = 10
        s.settings.evidence_retention_days = 10
        s.settings.operation_retention_days = 10
        old = "2020-01-01T00:00:00+00:00"
        expired = s.settings.plans_dir / "expired.json"
        expired.write_text(json.dumps({"plan_id": "expired", "status": "applied", "created_at": old}))
        pending = s.settings.plans_dir / "pending.json"
        pending.write_text(json.dumps({"plan_id": "pending", "status": "approved", "created_at": old}))
        ck = s.settings.checkpoints_dir / "expired"
        ck.mkdir()
        (ck / "manifest.json").write_text("{}")
        old_stamp = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(ck, (old_stamp, old_stamp))
        s.store.add_evidence([{
            "run_id": "old-run", "subject": "project", "check_id": "tests",
            "status": "passed", "detail": "", "duration_s": 0.1, "recorded_at": old,
        }])
        s.store.record_operation({
            "operation_id": "old-op", "kind": "test", "target": "project",
            "status": "passed", "started": old, "finished": old, "summary": {},
        })

        result = s.garbage_collect(now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["candidates"]["plans"], ["expired"])
        self.assertEqual(result["candidates"]["checkpoints"], ["expired"])
        self.assertEqual(result["candidates"]["evidence"], 1)
        self.assertEqual(result["candidates"]["operations"], 1)
        self.assertEqual(result["protected_plans"], ["pending"])
        self.assertTrue(expired.exists())
        self.assertTrue(pending.exists())
        self.assertTrue(ck.exists())
        self.assertEqual(len(s.store.list_evidence("project", "old-run")), 1)
        self.assertIsNotNone(s.store.get_operation("old-op"))

    def test_gc_apply_prunes_only_expired_terminal_data(self):
        s = self.services()
        s.settings.plan_retention_days = 10
        s.settings.checkpoint_retention_days = 10
        s.settings.evidence_retention_days = 10
        s.settings.operation_retention_days = 10
        old = "2020-01-01T00:00:00+00:00"
        expired = s.settings.plans_dir / "expired.json"
        expired.write_text(json.dumps({"plan_id": "expired", "status": "rolled_back", "created_at": old}))
        pending = s.settings.plans_dir / "pending.json"
        pending.write_text(json.dumps({"plan_id": "pending", "status": "planned", "created_at": old}))
        ck = s.settings.checkpoints_dir / "expired"
        ck.mkdir()
        (ck / "recovery.json").write_text("{}")
        old_stamp = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(ck, (old_stamp, old_stamp))
        s.store.add_evidence([{
            "run_id": "old-run", "subject": "project", "check_id": "tests",
            "status": "passed", "detail": "", "duration_s": 0.1, "recorded_at": old,
        }])
        s.store.record_operation({
            "operation_id": "old-op", "kind": "test", "target": "project",
            "status": "passed", "started": old, "finished": old, "summary": {},
        })

        result = s.garbage_collect(apply=True, now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertEqual(result["mode"], "applied")
        self.assertFalse(expired.exists())
        self.assertTrue(pending.exists())
        self.assertFalse(ck.exists())
        self.assertEqual(result["removed"], {"plans": 1, "checkpoints": 1})
        self.assertEqual(result["database_deleted"], {"evidence": 1, "operations": 1})
        self.assertEqual(s.store.list_evidence("project", "old-run"), [])
        self.assertIsNone(s.store.get_operation("old-op"))

    def test_retention_settings_reject_invalid_values(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "settings.toml").write_text("[retention]\nplan_retention_days = 0\n")
        with self.assertRaisesRegex(ValueError, "plan_retention_days"):
            ForgeSettings.load(self.home)


if __name__ == "__main__":
    unittest.main()
