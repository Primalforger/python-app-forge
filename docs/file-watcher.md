# File watcher and notifiers

FileWatcher uses standard-library polling; it adds no runtime dependency and
works consistently across operating systems. It reports created, modified and
deleted files relative to an existing watch root. Recursive mode is enabled by
default, symbolic links are not followed, and max_files bounds each scan.

    from app_forge.file_watcher import FileWatcher, QueueNotifier

    events = QueueNotifier(maxsize=500)
    watcher = FileWatcher("./workspace", events, interval=0.5)
    watcher.start()
    try:
        change = events.get(timeout=5)
    finally:
        watcher.stop()

The initial scan establishes a baseline by default. Set
start(emit_existing=True) to emit existing files as created events. Call
scan_once() for deterministic synchronous scans. The watcher thread is a
daemon and should still be stopped explicitly. Callbacks run on that thread;
use QueueNotifier to move processing elsewhere. Queue overflow raises
queue.Full; choose a capacity and consumer rate appropriate to the workload.
CompositeNotifier fans out to multiple notifiers in order. Notifier failures
are exposed as last_error and the polling loop continues.
