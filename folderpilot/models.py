"""Immutable values shared by scanning, comparison and execution."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from threading import Event


class SafetyError(RuntimeError):
    """An unsafe or stale request which must not be executed."""


class Cancelled(RuntimeError):
    pass


Progress = Callable[[str, int, int], None]


def checkpoint(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("用户取消任务")


@dataclass(frozen=True)
class Entry:
    kind: str
    size: int = 0
    mtime_ns: int = 0
    digest: str = ""


@dataclass(frozen=True)
class Snapshot:
    root: Path
    entries: dict[str, Entry]
    errors: tuple[str, ...] = ()
    recursive: bool = True
    extensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    category: str
    relative: str
    source: str = ""
    target: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Operation:
    action: str
    relative: str
    source: str = ""
    target: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Plan:
    id: str
    mode: str
    source: Snapshot
    target: Snapshot
    operations: tuple[Operation, ...]
    warnings: tuple[str, ...] = ()


@dataclass
class Outcome:
    task_id: str
    status: str
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
