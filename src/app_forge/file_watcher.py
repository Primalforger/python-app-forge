"""Bounded polling file watcher and composable change notifiers."""
from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FileChange:
    """A filesystem change observed beneath a watch root."""
    kind: str
    path: str
    size: int
    modified_ns: int


class ChangeNotifier(Protocol):
    def notify(self, change: FileChange) -> None: ...


class CallbackNotifier:
    """Deliver each change to a caller-provided callback."""
    def __init__(self, callback: Callable[[FileChange], None]) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        self.callback = callback

    def notify(self, change: FileChange) -> None:
        self.callback(change)


class QueueNotifier:
    """Publish changes to a bounded thread-safe queue."""
    def __init__(self, maxsize: int = 1000) -> None:
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or not 1 <= maxsize <= 1_000_000:
            raise ValueError("maxsize must be between 1 and 1000000")
        self.events: queue.Queue[FileChange] = queue.Queue(maxsize=maxsize)

    def notify(self, change: FileChange) -> None:
        self.events.put_nowait(change)

    def get(self, timeout: float | None = None) -> FileChange:
        return self.events.get(timeout=timeout)


class CompositeNotifier:
    """Fan out to multiple notifiers in declaration order."""
    def __init__(self, notifiers: Iterable[ChangeNotifier]) -> None:
        self.notifiers = tuple(notifiers)
        if any(notifier is None or not callable(getattr(notifier, "notify", None)) for notifier in self.notifiers):
            raise TypeError("each notifier must provide notify(change)")

    def notify(self, change: FileChange) -> None:
        for notifier in self.notifiers:
            notifier.notify(change)


class FileWatcher:
    """Poll a directory tree without following symlinks or exceeding file bounds.

    Callbacks execute on the watcher thread. Keep them short; use QueueNotifier
    to hand work to another thread. A notifier exception is captured in
    last_error and the polling loop continues.
    """
    def __init__(
        self, root: str | Path, notifier: ChangeNotifier, *,
        interval: float = 1.0, recursive: bool = True, max_files: int = 100_000,
    ) -> None:
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0.05 <= interval <= 3600:
            raise ValueError("interval must be between 0.05 and 3600 seconds")
        if not isinstance(recursive, bool):
            raise TypeError("recursive must be a boolean")
        if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= 1_000_000:
            raise ValueError("max_files must be between 1 and 1000000")
        if not callable(getattr(notifier, "notify", None)):
            raise TypeError("notifier must provide notify(change)")
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError("watch root must be an existing directory")
        self.notifier = notifier
        self.interval = float(interval)
        self.recursive = recursive
        self.max_files = max_files
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, tuple[int, int]] = {}
        self.last_error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _take_snapshot(self) -> dict[str, tuple[int, int]]:
        current: dict[str, tuple[int, int]] = {}
        if self.recursive:
            for directory, dirs, files in os.walk(self.root, followlinks=False):
                dirs[:] = sorted(name for name in dirs if not (Path(directory) / name).is_symlink())
                candidates = (Path(directory) / name for name in sorted(files))
                for path in candidates:
                    if path.is_symlink() or not path.is_file():
                        continue
                    info = path.stat()
                    current[path.relative_to(self.root).as_posix()] = (info.st_size, info.st_mtime_ns)
                    if len(current) > self.max_files:
                        raise RuntimeError("watch tree exceeds configured max_files")
        else:
            for path in sorted(self.root.iterdir()):
                if path.is_symlink() or not path.is_file():
                    continue
                info = path.stat()
                current[path.name] = (info.st_size, info.st_mtime_ns)
                if len(current) > self.max_files:
                    raise RuntimeError("watch directory exceeds configured max_files")
        return current

    def scan_once(self) -> list[FileChange]:
        """Compare one snapshot and synchronously publish its changes."""
        current = self._take_snapshot()
        previous = self._snapshot
        changes: list[FileChange] = []
        for name in sorted(current.keys() - previous.keys()):
            size, modified = current[name]
            changes.append(FileChange("created", name, size, modified))
        for name in sorted(current.keys() & previous.keys()):
            if current[name] != previous[name]:
                size, modified = current[name]
                changes.append(FileChange("modified", name, size, modified))
        for name in sorted(previous.keys() - current.keys()):
            size, modified = previous[name]
            changes.append(FileChange("deleted", name, size, modified))
        self._snapshot = current
        for change in changes:
            self.notifier.notify(change)
        return changes

    def start(self, *, emit_existing: bool = False) -> None:
        if not isinstance(emit_existing, bool):
            raise TypeError("emit_existing must be a boolean")
        if self.running:
            raise RuntimeError("file watcher is already running")
        self._stop.clear()
        self._snapshot = {} if emit_existing else self._take_snapshot()
        self.last_error = None
        self._thread = threading.Thread(target=self._run, name="app-forge-file-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 5.0) -> bool:
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0 or timeout == float("inf")):
            raise ValueError("timeout must be a finite non-negative number or None")
        self._stop.set()
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout)
        if not thread.is_alive():
            self._thread = None
            return True
        return False

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.scan_once()
            except Exception as error:
                self.last_error = error
