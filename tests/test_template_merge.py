import unittest

from app_forge.templates.merge import merge_file_maps, merge_text


class ThreeWayTextMergeTests(unittest.TestCase):
    def test_local_only_edit_is_preserved(self):
        result = merge_text("one\ntwo\n", "ONE\ntwo\n", "one\ntwo\nthree\n")
        self.assertTrue(result.clean)
        self.assertEqual(result.text, "ONE\ntwo\nthree\n")

    def test_upstream_only_edit_is_applied(self):
        result = merge_text("one\ntwo\n", "one\ntwo\n", "one\nTWO\n")
        self.assertEqual(result.text, "one\nTWO\n")

    def test_disjoint_edits_merge(self):
        result = merge_text("a\nb\nc\n", "A\nb\nc\n", "a\nb\nC\n")
        self.assertTrue(result.clean)
        self.assertEqual(result.text, "A\nb\nC\n")

    def test_same_edit_from_both_sides_is_not_a_conflict(self):
        result = merge_text("a\nb\n", "a\nB\n", "a\nB\n")
        self.assertTrue(result.clean)
        self.assertEqual(result.text, "a\nB\n")

    def test_overlapping_edits_are_reported_without_partial_output(self):
        result = merge_text("a\nb\nc\n", "a\nLOCAL\nc\n", "a\nUPSTREAM\nc\n")
        self.assertFalse(result.clean)
        self.assertIsNone(result.text)
        self.assertEqual(len(result.conflicts), 1)

    def test_concurrent_insertions_at_same_boundary_conflict(self):
        result = merge_text("a\n", "local\na\n", "upstream\na\n")
        self.assertFalse(result.clean)

    def test_edit_and_append_preserve_missing_final_newline(self):
        result = merge_text("first\n", "local first\n", "first\nsecond")
        self.assertTrue(result.clean)
        self.assertEqual(result.text, "local first\nsecond")


class ThreeWayFileTreeMergeTests(unittest.TestCase):
    def test_additions_from_both_sides_are_combined(self):
        result = merge_file_maps(
            {"base.py": "x\n"},
            {"base.py": "x\n", "local.py": "l\n"},
            {"base.py": "x\n", "upstream.py": "u\n"},
        )
        self.assertTrue(result.clean)
        self.assertEqual(set(result.files), {"base.py", "local.py", "upstream.py"})

    def test_identical_concurrent_addition_is_kept_once(self):
        result = merge_file_maps({}, {"new.py": "x\n"}, {"new.py": "x\n"})
        self.assertEqual(result.files, {"new.py": "x\n"})
        self.assertTrue(result.clean)

    def test_different_concurrent_addition_conflicts(self):
        result = merge_file_maps({}, {"new.py": "local\n"}, {"new.py": "upstream\n"})
        self.assertEqual(result.conflicts[0].kind, "add-add")

    def test_local_deletion_survives_unchanged_upstream(self):
        result = merge_file_maps({"old.py": "x\n"}, {}, {"old.py": "x\n"})
        self.assertTrue(result.clean)
        self.assertNotIn("old.py", result.files)

    def test_delete_vs_upstream_modification_conflicts(self):
        result = merge_file_maps({"old.py": "x\n"}, {}, {"old.py": "changed\n"})
        self.assertEqual(result.conflicts[0].kind, "delete-modify")

    def test_content_conflict_is_path_scoped(self):
        result = merge_file_maps(
            {"a.py": "x\n", "b.py": "y\n"},
            {"a.py": "local\n", "b.py": "y\n"},
            {"a.py": "upstream\n", "b.py": "Y\n"},
        )
        self.assertEqual([(c.path, c.kind) for c in result.conflicts],
                         [("a.py", "content-conflict")])
        self.assertEqual(result.files, {"b.py": "Y\n"})


if __name__ == "__main__":
    unittest.main()
