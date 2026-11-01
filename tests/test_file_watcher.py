from __future__ import annotations

import queue

import pytest

from app_forge.file_watcher import (
    CallbackNotifier, CompositeNotifier, FileChange, FileWatcher, QueueNotifier,
)


def test_scan_reports_created_modified_and_deleted(tmp_path) -> None:
    events = []
    watcher = FileWatcher(tmp_path, CallbackNotifier(events.append), interval=0.05)
    assert watcher.scan_once() == []
    (tmp_path / "a.txt").write_text("one")
    assert [event.kind for event in watcher.scan_once()] == ["created"]
    (tmp_path / "a.txt").write_text("a longer value")
    assert [event.kind for event in watcher.scan_once()] == ["modified"]
    (tmp_path / "a.txt").unlink()
    assert [event.kind for event in watcher.scan_once()] == ["deleted"]
    assert [event.kind for event in events] == ["created", "modified", "deleted"]


def test_recursive_and_non_recursive_modes(tmp_path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside").write_text("x")
    assert FileWatcher(tmp_path, QueueNotifier()).scan_once()[0].path == "nested/inside"
    assert FileWatcher(tmp_path, QueueNotifier(), recursive=False).scan_once() == []


def test_symlinks_are_not_followed(tmp_path) -> None:
    outside = tmp_path.parent / "watch-outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret").write_text("secret")
    try:
        (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert FileWatcher(tmp_path, QueueNotifier()).scan_once() == []


def test_queue_and_composite_notifiers() -> None:
    first, second = QueueNotifier(2), QueueNotifier(2)
    change = FileChange("created", "a", 1, 2)
    CompositeNotifier([first, second]).notify(change)
    assert first.get() == change
    assert second.get() == change


def test_queue_notifier_is_bounded() -> None:
    notifier = QueueNotifier(1)
    event = FileChange("created", "a", 1, 1)
    notifier.notify(event)
    with pytest.raises(queue.Full):
        notifier.notify(event)


def test_watcher_thread_detects_change_and_stops(tmp_path) -> None:
    notifier = QueueNotifier()
    watcher = FileWatcher(tmp_path, notifier, interval=0.05)
    watcher.start()
    (tmp_path / "new").write_text("data")
    assert notifier.get(timeout=2).kind == "created"
    assert watcher.stop(timeout=2)
    assert not watcher.running
    with pytest.raises(RuntimeError, match="already running"):
        watcher.start()
    watcher.start()
    assert watcher.stop(timeout=2)


def test_start_can_emit_existing_files(tmp_path) -> None:
    (tmp_path / "present").write_text("x")
    notifier = QueueNotifier()
    watcher = FileWatcher(tmp_path, notifier, interval=0.05)
    watcher.start(emit_existing=True)
    assert notifier.get(timeout=2).path == "present"
    assert watcher.stop(timeout=2)


@pytest.mark.parametrize("kwargs", [
    {"interval": 0}, {"interval": 4000}, {"max_files": 0}, {"recursive": 1},
])
def test_invalid_configuration_rejected(tmp_path, kwargs) -> None:
    with pytest.raises((TypeError, ValueError)):
        FileWatcher(tmp_path, QueueNotifier(), **kwargs)


def test_file_limit_is_enforced(tmp_path) -> None:
    (tmp_path / "a").write_text("a")
    (tmp_path / "b").write_text("b")
    with pytest.raises(RuntimeError, match="max_files"):
        FileWatcher(tmp_path, QueueNotifier(), max_files=1).scan_once()
