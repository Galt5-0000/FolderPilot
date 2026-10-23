"""The only module permitted to change business files or quarantine payloads."""
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from uuid import uuid4
from .compare import CHUNK_SIZE, fingerprint
from .models import Cancelled, Entry, Outcome, Plan, Progress, SafetyError, checkpoint
from .planning import revalidate
from .safety import child, inside, safe_path, validate_roots
from .storage import Vault, now


def token(value) -> str:
    """Bind approval to the complete preview, including expected file states."""
    data = asdict(value)
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_state(path: Path, expected: Entry | None, cancel: Event | None = None) -> None:
    safe_path(path)
    if expected is None:
        if os.path.lexists(path):
            raise SafetyError(f"路径被占用：{path}")
    elif not path.exists() or fingerprint(path, True, cancel) != expected:
        raise SafetyError(f"文件已变化或无法访问：{path}")


@dataclass(frozen=True)
class MaintenancePlan:
    id: str
    action: str
    item_id: str
    original: str
    stored: str
    expected: Entry
    current: Entry | None
    item_status: str


class Engine:
    def __init__(self, vault: Vault):
        self.vault = vault

    def _available(self) -> None:
        if self.vault.jobs(pending=True):
            raise SafetyError("发现中断/未完成任务，请先在隔离区查看并人工核查，禁止自动重复执行")

    def _start(self, task: str, mode: str) -> None:
        self._available()
        with self.vault.connect() as db:
            if db.execute("SELECT 1 FROM jobs WHERE id=?", (task,)).fetchone():
                raise SafetyError("此计划已经执行过，请重新扫描")
            db.execute("INSERT INTO jobs(id,mode,status,started) VALUES(?,?,?,?)", (task, mode, "running", now()))
        self.vault.event(task, "开始", mode)

    def _finish(self, outcome: Outcome) -> Outcome:
        with self.vault.connect() as db:
            db.execute("UPDATE jobs SET status=?,ended=?,summary=? WHERE id=?",
                       (outcome.status, now(), json.dumps(asdict(outcome), ensure_ascii=False), outcome.task_id))
        self.vault.event(outcome.task_id, "结束", json.dumps(asdict(outcome), ensure_ascii=False))
        return outcome

    def _stage(self, source: Path, target: Path, expected: Entry, cancel: Event | None) -> Path:
        """Copy to a same-directory private file, fsync, then independently hash."""
        require_state(source, expected, cancel)
        safe_path(target.parent)
        if not target.parent.is_dir():
            raise SafetyError(f"目标父目录不存在：{target.parent}")
        if shutil.disk_usage(target.parent).free < expected.size + 1024 * 1024:
            raise SafetyError("可用磁盘空间不足（含最小安全余量）")
        temporary = target.parent / (".folderpilot-tmp-" + uuid4().hex)
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                while block := reader.read(CHUNK_SIZE):
                    checkpoint(cancel)
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            actual = fingerprint(temporary, True, cancel)
            if (actual.size, actual.digest) != (expected.size, expected.digest):
                raise SafetyError("临时副本 SHA-256 校验失败")
            require_state(source, expected, cancel)
            shutil.copystat(source, temporary, follow_symlinks=False)
            checkpoint(cancel)
            return temporary
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            raise

    def _install(self, temporary: Path, target: Path, current: Entry | None,
                 cancel: Event | None) -> None:
        try:
            checkpoint(cancel)
            require_state(target, current, cancel)
            if current is None:
                # Windows rename refuses an existing destination; POSIX link is no-clobber.
                if os.name == "nt":
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
                    temporary.unlink()
            else:
                os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _archive(self, task: str, path: Path, expected: Entry, kind: str,
                 cancel: Event | None) -> dict:
        require_state(path, expected, cancel)
        item = self.vault.reserve(task, path, expected, kind)
        if expected.kind == "file":
            stored = safe_path(Path(item["stored"]))
            temporary = self._stage(path, stored, expected, cancel)
            self._install(temporary, stored, None, cancel)
        self.vault.item_status(item["id"], "ready")
        self.vault.event(task, "保存隔离副本", json.dumps(item, ensure_ascii=False))
        return item

    def execute(self, plan: Plan, *, confirmation: str, cancel: Event | None = None,
                progress: Progress | None = None) -> Outcome:
        if confirmation != token(plan):
            raise SafetyError("必须确认当前完整操作预览")
        with self.vault.locked():
            validate_roots(plan.source.root, plan.target.root, self.vault.root)
            self._available()
            checkpoint(cancel)
            revalidate(plan.source, cancel)
            revalidate(plan.target, cancel)
            self._start(plan.id, plan.mode)
            result = Outcome(plan.id, "completed")
            for sequence, operation in enumerate(plan.operations):
                try:
                    checkpoint(cancel)
                    target = child(plan.target.root, operation.relative)
                    if str(target) != operation.target:
                        raise SafetyError("操作路径与计划根目录不一致")
                    expected = plan.target.entries.get(operation.relative)
                    source_entry = plan.source.entries.get(operation.relative)
                    with self.vault.connect() as db:
                        db.execute("INSERT INTO steps VALUES(?,?,?,?,?,?,?)",
                                   (plan.id, sequence, operation.action, operation.source, operation.target, "running", operation.reason))
                    if operation.action == "skip":
                        result.skipped += 1
                    elif operation.action == "mkdir":
                        require_state(target, None, cancel)
                        target.mkdir()
                        result.completed += 1
                    elif operation.action in {"copy", "update"}:
                        source = child(plan.source.root, operation.relative)
                        if str(source) != operation.source or source_entry is None:
                            raise SafetyError("源文件不属于当前计划")
                        require_state(target, expected, cancel)
                        temporary = self._stage(source, target, source_entry, cancel)
                        try:
                            if expected:
                                self._archive(plan.id, target, expected, "overwrite", cancel)
                            self._install(temporary, target, expected, cancel)
                        finally:
                            if temporary.exists():
                                temporary.unlink()
                        result.completed += 1
                    elif operation.action == "quarantine":
                        if expected is None or expected.kind != "file":
                            raise SafetyError("隔离操作缺少文件校验基线")
                        self._archive(plan.id, target, expected, "cleanup", cancel)
                        require_state(target, expected, cancel)
                        checkpoint(cancel)
                        target.unlink()
                        result.completed += 1
                    elif operation.action == "rmdir":
                        require_state(target, Entry("dir"), cancel)
                        self._archive(plan.id, target, Entry("dir"), "directory", cancel)
                        checkpoint(cancel)
                        target.rmdir()  # Never recursively delete unknown children.
                        result.completed += 1
                    else:
                        raise SafetyError(f"未知操作：{operation.action}")
                    with self.vault.connect() as db:
                        db.execute("UPDATE steps SET status='done' WHERE task_id=? AND sequence=?", (plan.id, sequence))
                    self.vault.event(plan.id, operation.action, json.dumps(asdict(operation), ensure_ascii=False))
                    if progress:
                        progress(operation.target, sequence + 1, len(plan.operations))
                except Exception as exc:
                    cancelled = isinstance(exc, Cancelled)
                    result.status = "cancelled" if cancelled else ("partial" if result.completed else "failed")
                    result.failed += 0 if cancelled else 1
                    result.errors.append(f"{operation.target}: {type(exc).__name__}: {exc}")
                    with self.vault.connect() as db:
                        db.execute("UPDATE steps SET status=?,detail=? WHERE task_id=? AND sequence=?",
                                   ("cancelled" if cancelled else "failed", str(exc), plan.id, sequence))
                    self.vault.event(plan.id, "取消" if cancelled else "失败", result.errors[-1])
                    break
            return self._finish(result)

    def maintenance_plan(self, item_id: str, action: str = "restore") -> MaintenancePlan:
        if action not in {"restore", "purge"}:
            raise SafetyError("未知隔离维护操作")
        item = self.vault.get(item_id)
        if item["status"] == "purged":
            raise SafetyError("此隔离副本已经永久删除")
        expected = Entry(**json.loads(item["fingerprint"]))
        original = safe_path(Path(item["original"]))
        if inside(original, self.vault.root):
            raise SafetyError("原始路径不能位于隔离存储中")
        if expected.kind == "file":
            stored = safe_path(Path(item["stored"]))
            if stored.parent != self.vault.objects or stored.name != item_id:
                raise SafetyError("隔离元数据路径异常")
            actual = fingerprint(stored)
            if (actual.size, actual.digest) != (expected.size, expected.digest):
                raise SafetyError("隔离副本完整性校验失败")
        current = fingerprint(original) if original.exists() else None
        if current and current.kind != expected.kind:
            raise SafetyError("恢复目标的文件/目录类型冲突")
        return MaintenancePlan(uuid4().hex, action, item_id, str(original), item["stored"], expected, current, item["status"])

    def maintain(self, plan: MaintenancePlan, *, confirmation: str,
                 overwrite_confirmation: bool = False, permanent_confirmation: str = "",
                 cancel: Event | None = None) -> Outcome:
        if confirmation != token(plan):
            raise SafetyError("必须确认当前隔离操作预览")
        if plan.action == "restore" and plan.current and not overwrite_confirmation:
            raise SafetyError("恢复路径已占用，必须单独明确确认覆盖")
        if plan.action == "purge" and permanent_confirmation != "永久删除":
            raise SafetyError("永久删除需要二次确认并输入“永久删除”")
        with self.vault.locked():
            self._available()
            fresh = self.maintenance_plan(plan.item_id, plan.action)
            if any(getattr(fresh, field) != getattr(plan, field) for field in
                   ("original", "stored", "expected", "current", "item_status")):
                raise SafetyError("隔离记录或恢复目标已变化，请重新预览")
            checkpoint(cancel)
            self._start(plan.id, plan.action)
            result = Outcome(plan.id, "completed")
            try:
                target = safe_path(Path(plan.original))
                if plan.action == "purge":
                    if plan.expected.kind == "file":
                        Path(plan.stored).unlink()
                    self.vault.item_status(plan.item_id, "purged")
                else:
                    require_state(target, plan.current, cancel)
                    safe_path(target.parent)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if plan.expected.kind == "dir":
                        target.mkdir(exist_ok=True)
                    else:
                        stored = Path(plan.stored)
                        stored_entry = fingerprint(stored)
                        temporary = self._stage(stored, target, stored_entry, cancel)
                        try:
                            if plan.current:
                                self._archive(plan.id, target, plan.current, "restore_overwrite", cancel)
                            self._install(temporary, target, plan.current, cancel)
                        finally:
                            if temporary.exists():
                                temporary.unlink()
                    self.vault.item_status(plan.item_id, "restored")
                self.vault.event(plan.id, plan.action, json.dumps(asdict(plan), default=str, ensure_ascii=False))
                result.completed = 1
            except Exception as exc:
                result.status = "cancelled" if isinstance(exc, Cancelled) else "failed"
                result.failed = 0 if isinstance(exc, Cancelled) else 1
                result.errors.append(f"{type(exc).__name__}: {exc}")
                self.vault.event(plan.id, "失败", result.errors[-1])
            return self._finish(result)
