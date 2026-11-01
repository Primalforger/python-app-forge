import unittest

from app_forge.undo import UndoRedoStack


class Change:
    def __init__(self, state, value):
        self.state, self.value = state, value

    def execute(self):
        self.state.append(self.value)

    def undo(self):
        self.state.pop()


class FailingChange(Change):
    def execute(self):
        raise RuntimeError("execute failed")


class UndoRedoStackTests(unittest.TestCase):
    def test_execute_undo_redo_round_trip(self):
        state, history = [], UndoRedoStack()
        history.execute(Change(state, "a"))
        history.execute(Change(state, "b"))
        self.assertEqual(state, ["a", "b"])
        self.assertTrue(history.undo())
        self.assertEqual(state, ["a"])
        self.assertTrue(history.can_redo)
        self.assertTrue(history.redo())
        self.assertEqual(state, ["a", "b"])
        self.assertFalse(history.can_redo)

    def test_new_command_discards_redo_branch(self):
        state, history = [], UndoRedoStack()
        history.execute(Change(state, 1))
        history.undo()
        history.execute(Change(state, 2))
        self.assertEqual(state, [2])
        self.assertFalse(history.can_redo)

    def test_history_is_bounded(self):
        state, history = [], UndoRedoStack(max_history=2)
        for value in range(3):
            history.execute(Change(state, value))
        self.assertEqual(history.undo_count, 2)
        self.assertTrue(history.undo())
        self.assertTrue(history.undo())
        self.assertFalse(history.undo())
        self.assertEqual(state, [0])

    def test_failed_operations_do_not_move_history(self):
        state, history = [], UndoRedoStack()
        with self.assertRaises(RuntimeError):
            history.execute(FailingChange(state, "bad"))
        self.assertFalse(history.can_undo)
        history.execute(Change(state, "ok"))
        command = history._undo[-1]
        command.undo = lambda: (_ for _ in ()).throw(RuntimeError("undo failed"))
        with self.assertRaises(RuntimeError):
            history.undo()
        self.assertEqual(history.undo_count, 1)
        self.assertEqual(history.redo_count, 0)

    def test_empty_operations_clear_and_validation(self):
        history = UndoRedoStack()
        self.assertFalse(history.undo())
        self.assertFalse(history.redo())
        with self.assertRaises(ValueError):
            UndoRedoStack(0)
        with self.assertRaises(ValueError):
            UndoRedoStack(True)
        with self.assertRaises(TypeError):
            history.execute(object())
        state = []
        history.execute(Change(state, 1))
        history.undo()
        history.clear()
        self.assertFalse(history.can_undo)
        self.assertFalse(history.can_redo)


if __name__ == "__main__":
    unittest.main()
