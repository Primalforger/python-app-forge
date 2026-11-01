# Local file store

`LocalFileStore(root)` confines application file operations to a configured
directory. Paths are relative POSIX paths; absolute paths, traversal, drive
prefixes, backslashes and symlink components are rejected.

The API supports byte/text reads and writes, deterministic file listing,
directory creation, and file deletion. Writes use a same-directory temporary
file, flush and fsync it, then atomically replace the destination. Individual
files are bounded by `max_file_bytes` (16 MiB by default, configurable up to
1 GiB). Listing is non-recursive unless `recursive=True`.

This is a path-safety abstraction, not a sandbox against a hostile process
that can concurrently mutate the store root. Keep the root private to the
application and use OS permissions or process isolation for adversarial
workloads. Symlinks are rejected rather than followed.
