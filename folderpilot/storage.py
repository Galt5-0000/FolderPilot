"""Durable SQLite journal, quarantine catalog and cross-process exclusion."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from dataclasses import asdict
from .models import Entry, SafetyError
from .safety import safe_path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Vault:
    """Quarantine is recoverable storage, not a fault-proof backup system."""

    def __init__(self, root: Path):
        self.root = safe_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        safe_path(self.root / ".folderpilot-vault").touch(exist_ok=True)
        self.objects = safe_path(self.root / "objects")
        self.objects.mkdir(exist_ok=True)
        self.database = self.root / "journal.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL,
                    started TEXT NOT NULL, ended TEXT, summary TEXT);
                CREATE TABLE IF NOT EXISTS steps (
                    task_id TEXT, sequence INTEGER, action TEXT, source TEXT, target TEXT,
                    status TEXT, detail TEXT, PRIMARY KEY(task_id, sequence));
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, task_id TEXT, original TEXT, stored TEXT,
                    created TEXT, kind TEXT, fingerprint TEXT, status TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, created TEXT, task_id TEXT, kind TEXT, detail TEXT);
            """)

    @contextmanager
    def connect(self):
        safe_path(self.database)
        db = sqlite3.connect(self.database, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def locked(self):
        """Do not permit a second process to mutate the same catalog concurrently."""
        path = safe_path(self.root / "execution.lock")
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SafetyError("另一个任务正在操作此隔离存储") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def event(self, task: str, kind: str, detail: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO events(created,task_id,kind,detail) VALUES(?,?,?,?)", (now(), task, kind, detail))

    def jobs(self, pending: bool = False) -> list[dict]:
        with self.connect() as db:
            query = "SELECT * FROM jobs" + (" WHERE status='running'" if pending else "") + " ORDER BY started DESC"
            return [dict(row) for row in db.execute(query)]

    def items(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM items ORDER BY created DESC, id")]

    def get(self, item_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise SafetyError("隔离记录不存在")
        return dict(row)

    def reserve(self, task: str, original: Path, entry: Entry, kind: str) -> dict:
        item_id = uuid4().hex
        stored = str(self.objects / item_id) if entry.kind == "file" else ""
        with self.connect() as db:
            db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?)",
                       (item_id, task, str(original), stored, now(), kind, json.dumps(asdict(entry)), "preparing"))
        return self.get(item_id)

    def item_status(self, item_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))

    def logs(self, limit: int = 2000) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def review_interrupted(self, task_id: str, *, confirmed: bool) -> None:
        if not confirmed:
            raise SafetyError("需先人工核查未完成任务、业务目录和隔离记录")
        with self.locked(), self.connect() as db:
            db.execute("UPDATE jobs SET status='reviewed',ended=? WHERE id=? AND status='running'", (now(), task_id))
        self.event(task_id, "人工核查", "用户确认已检查中断任务；不重放任何文件操作")
