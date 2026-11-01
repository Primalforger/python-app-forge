"""Tests for the hash-chained audit log."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from app_forge.audit_log import AuditLogError, HashChainedAuditLog


class AuditLogTests(unittest.TestCase):
    def test_empty_log_verifies_and_appends_a_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = HashChainedAuditLog(Path(directory) / "audit.jsonl")
            self.assertTrue(log.verify()["ok"])
            first = log.append({"action": "created"}, actor="tester", timestamp="2026-01-01T00:00:00+00:00")
            second = log.append({"action": "updated"}, actor="tester", timestamp="2026-01-01T00:00:01+00:00")
            report = log.verify()
            self.assertTrue(report["ok"])
            self.assertEqual(report["records"], 2)
            self.assertEqual(second["previous_hash"], first["hash"])
            self.assertEqual(report["head"], second["hash"])

    def test_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            log = HashChainedAuditLog(path)
            log.append({"action": "safe"}, actor="tester")
            record = json.loads(path.read_text(encoding="utf-8"))
            record["event"]["action"] = "tampered"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            report = log.verify()
            self.assertFalse(report["ok"])
            self.assertIn("hash mismatch", report["error"])

    def test_truncation_and_malformed_records_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            path.write_text('{"partial":', encoding="utf-8")
            report = HashChainedAuditLog(path).verify()
            self.assertFalse(report["ok"])
            self.assertEqual(report["records"], 0)

    def test_invalid_log_cannot_be_appended(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(AuditLogError):
                HashChainedAuditLog(path).append({"action": "x"}, actor="tester")

    def test_validation_rejects_non_json_and_bad_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = HashChainedAuditLog(Path(directory) / "audit.jsonl")
            with self.assertRaises(ValueError):
                log.append({"value": float("nan")}, actor="tester")
            with self.assertRaises(ValueError):
                log.append({"ok": True}, actor="")
            with self.assertRaises(ValueError):
                log.append({"ok": True}, actor="tester", timestamp="yesterday")

    def test_concurrent_appends_preserve_sequence_and_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = HashChainedAuditLog(Path(directory) / "audit.jsonl")
            errors: list[BaseException] = []
            def write(index: int) -> None:
                try:
                    log.append({"index": index}, actor="worker")
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=write, args=(i,)) for i in range(24)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            report = log.verify()
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["records"], 24)


if __name__ == "__main__":
    unittest.main()
