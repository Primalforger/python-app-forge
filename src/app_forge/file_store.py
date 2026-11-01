"""Root-confined local file storage with atomic writes and symlink rejection.

Paths are always relative to an explicitly configured root. The store is
intended for application data, not as a replacement for OS-level isolation:
callers must still protect the root directory from hostile concurrent writers.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class FileInfo:
    """Metadata for a regular file beneath a store root."""
    path: str
    size: int
    modified_ns: int


class FileStoreError(ValueError):
    """A file-store operation violates its path or content policy."""


class LocalFileStore:
    """A bounded local file store that never follows symlinks beneath its root."""

    def __init__(self, root: str | Path, *, max_file_bytes: int = 16_777_216) -> None:
        if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or not 1 <= max_file_bytes <= 1_073_741_824:
            raise ValueError("max_file_bytes must be an integer from 1 to 1073741824")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise FileStoreError("file-store root must be a directory")
        self.max_file_bytes = max_file_bytes

    @staticmethod
    def _relative(path: str | Path) -> PurePosixPath:
        if not isinstance(path, (str, Path)):
            raise TypeError("file path must be a string or Path")
        raw = str(path)
        if not raw or raw != raw.strip() or "\x00" in raw or "\\" in raw:
            raise FileStoreError("path must be a non-empty relative POSIX path")
        candidate = PurePosixPath(raw)
        if candidate.is_absolute() or any(part in ("", ".", "..") for part in raw.split("/")):
            raise FileStoreError("absolute paths, traversal and empty path segments are not allowed")
        if candidate.parts and ":" in candidate.parts[0]:
            raise FileStoreError("drive-qualified paths are not allowed")
        return candidate

    def _resolve(self, path: str | Path, *, allow_missing: bool = False) -> Path:
        relative = self._relative(path)
        current = self.root
        for index, part in enumerate(relative.parts):
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                if allow_missing:
                    # Remaining parents are checked as they are created/accessed.
                    continue
                raise FileNotFoundError(str(path)) from None
            if current.is_symlink():
                raise FileStoreError(f"symlinks are not allowed in file-store paths: {relative}")
            if index < len(relative.parts) - 1 and not current.is_dir():
                raise FileStoreError(f"parent path is not a directory: {relative}")
        try:
            current.resolve(strict=False).relative_to(self.root)
        except ValueError as exc:
            raise FileStoreError("resolved path escapes the file-store root") from exc
        return current

    def read_bytes(self, path: str | Path) -> bytes:
        target = self._resolve(path)
        info = target.lstat()
        if not target.is_file() or info.st_size > self.max_file_bytes:
            raise FileStoreError("target must be a regular file within the configured size limit")
        data = target.read_bytes()
        if len(data) > self.max_file_bytes:
            raise FileStoreError("file exceeds the configured size limit")
        return data

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    def write_bytes(self, path: str | Path, data: bytes) -> FileInfo:
        if not isinstance(data, bytes):
            raise TypeError("file content must be bytes")
        if len(data) > self.max_file_bytes:
            raise FileStoreError("content exceeds the configured size limit")
        target = self._resolve(path, allow_missing=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-check after directory creation so pre-existing symlink parents fail closed.
        target = self._resolve(path, allow_missing=True)
        if target.exists() or target.is_symlink():
            info = target.lstat()
            if target.is_symlink() or not target.is_file():
                raise FileStoreError("writes may only replace regular files")
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Refuse a target that changed to a symlink while the temporary file was written.
            if target.is_symlink():
                raise FileStoreError("refusing to replace a symlink")
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        info = target.stat()
        return FileInfo(str(self._relative(path)), info.st_size, info.st_mtime_ns)

    def write_text(self, path: str | Path, text: str, *, encoding: str = "utf-8") -> FileInfo:
        if not isinstance(text, str):
            raise TypeError("text content must be a string")
        return self.write_bytes(path, text.encode(encoding))

    def list(self, path: str | Path = ".", *, recursive: bool = False) -> list[FileInfo]:
        if path == ".":
            directory = self.root
            prefix = ""
        else:
            directory = self._resolve(path)
            prefix = str(self._relative(path)) + "/"
        if not directory.is_dir() or directory.is_symlink():
            raise FileStoreError("list target must be a real directory")
        results: list[FileInfo] = []
        iterator = directory.rglob("*") if recursive else directory.iterdir()
        for item in iterator:
            if item.is_symlink():
                raise FileStoreError(f"symlink encountered while listing: {item.relative_to(self.root)}")
            if item.is_file():
                info = item.stat()
                if info.st_size > self.max_file_bytes:
                    raise FileStoreError(f"file exceeds configured size limit: {item.relative_to(self.root)}")
                relative = prefix + item.relative_to(directory).as_posix()
                results.append(FileInfo(relative, info.st_size, info.st_mtime_ns))
        return sorted(results, key=lambda entry: entry.path)

    def delete(self, path: str | Path, *, missing_ok: bool = False) -> bool:
        try:
            target = self._resolve(path)
        except FileNotFoundError:
            if missing_ok:
                return False
            raise
        if target.is_symlink() or not target.is_file():
            raise FileStoreError("delete target must be a regular file")
        target.unlink()
        return True

    def mkdir(self, path: str | Path) -> Path:
        target = self._resolve(path, allow_missing=True)
        target.mkdir(parents=True, exist_ok=True)
        # Resolve again to reject any symlink component.
        return self._resolve(path)
