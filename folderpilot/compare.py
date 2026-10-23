"""Content comparison is independent from name matching."""
import hashlib
from pathlib import Path
from threading import Event
from .models import Entry, SafetyError, checkpoint
from .safety import safe_path

CHUNK_SIZE = 1024 * 1024


def fingerprint(path: Path, exact: bool = True, cancel: Event | None = None) -> Entry:
    safe_path(path)
    before = path.stat()
    if path.is_dir():
        return Entry("dir")
    if not path.is_file():
        raise SafetyError(f"不支持的文件类型：{path}")
    digest = ""
    if exact:
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(CHUNK_SIZE):
                checkpoint(cancel)
                hasher.update(block)
        digest = hasher.hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise SafetyError(f"读取期间文件发生变化：{path}")
    return Entry("file", after.st_size, after.st_mtime_ns, digest)


def same_content(left: Entry, right: Entry, mode: str = "exact") -> bool:
    if left.kind != right.kind:
        return False
    if left.kind == "dir":
        return True
    if mode == "quick":
        return (left.size, left.mtime_ns) == (right.size, right.mtime_ns)
    if mode != "exact" or not left.digest or not right.digest:
        raise SafetyError("精确比较需要新计算的 SHA-256")
    return left.size == right.size and left.digest == right.digest
