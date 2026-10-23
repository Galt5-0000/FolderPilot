import json
import os
from dataclasses import replace
from pathlib import Path
from threading import Event
import pytest
from folderpilot.engine import token
from folderpilot.models import SafetyError
from folderpilot.planning import cleanup_plan, sync_plan
from folderpilot.scan import scan
from conftest import write, snapshots


def execute(engine, plan, **kwargs):
    return engine.execute(plan, confirmation=token(plan), **kwargs)


def test_safe_complete_preserves_extra_and_copies_empty_dirs(folders, engine):
    a, b = folders
    write(a, "nested/new.txt", "中文内容")
    (a / "empty/nested").mkdir(parents=True)
    write(b, "extra.txt", "keep")
    outcome = execute(engine, sync_plan(*snapshots(folders)))
    assert outcome.status == "completed"
    assert (b / "nested/new.txt").read_bytes() == (a / "nested/new.txt").read_bytes()
    assert (b / "extra.txt").read_text() == "keep"
    assert (b / "empty/nested").is_dir()


def test_mirror_quarantine_and_empty_directory_restore(folders, engine):
    write(folders[0], "keep")
    write(folders[1], "extra/sub/file", "preserve me")
    (folders[1] / "empty").mkdir()
    plan = sync_plan(*snapshots(folders), mirror=True)
    assert any(o.action == "quarantine" for o in plan.operations)
    with pytest.raises(SafetyError):
        engine.execute(plan, confirmation="")
    assert execute(engine, plan).status == "completed"
    assert set(scan(folders[0]).entries) == set(scan(folders[1]).entries)
    record = next(i for i in engine.vault.items() if i["kind"] == "cleanup")
    restore = engine.maintenance_plan(record["id"])
    assert engine.maintain(restore, confirmation=token(restore)).completed == 1
    assert Path(record["original"]).read_text() == "preserve me"
    empty = next(i for i in engine.vault.items() if i["original"].endswith("empty"))
    restore = engine.maintenance_plan(empty["id"])
    engine.maintain(restore, confirmation=token(restore))
    assert Path(empty["original"]).is_dir()


def test_update_old_version_and_restore_conflict(folders, engine):
    a, b = folders
    write(a, "same.txt", "new")
    write(b, "same.txt", "old")
    assert execute(engine, sync_plan(*snapshots(folders))).completed == 1
    item = engine.vault.items()[0]
    assert Path(item["stored"]).read_text() == "old"
    restore = engine.maintenance_plan(item["id"])
    with pytest.raises(SafetyError, match="单独明确确认"):
        engine.maintain(restore, confirmation=token(restore))
    assert engine.maintain(restore, confirmation=token(restore), overwrite_confirmation=True).completed == 1
    assert (b / "same.txt").read_text() == "old"
    assert any(Path(i["stored"]).read_text() == "new" for i in engine.vault.items())


@pytest.mark.parametrize("side", [0, 1])
def test_stale_scan_blocks_before_any_write(folders, engine, side):
    write(folders[0], "file", "source")
    write(folders[1], "file", "target")
    plan = sync_plan(*snapshots(folders))
    write(folders[side], "file", "changed")
    with pytest.raises(SafetyError, match="发生变化"):
        execute(engine, plan)
    assert not engine.vault.items()


def test_metadata_preserving_change_detected(folders, engine):
    path = write(folders[0], "x", "abc")
    plan = sync_plan(*snapshots(folders))
    stamp = path.stat().st_mtime_ns
    path.write_text("def")
    os.utime(path, ns=(stamp, stamp))
    with pytest.raises(SafetyError):
        execute(engine, plan)


def test_copy_failure_partial_and_log(folders, engine, monkeypatch):
    write(folders[0], "a")
    write(folders[0], "b")
    real = engine._stage
    def fail(source, target, expected, cancel):
        if source.name == "b":
            raise PermissionError("模拟文件占用或复制失败")
        return real(source, target, expected, cancel)
    monkeypatch.setattr(engine, "_stage", fail)
    result = execute(engine, sync_plan(*snapshots(folders)))
    assert (result.status, result.completed, result.failed) == ("partial", 1, 1)
    assert (folders[1] / "a").exists() and not (folders[1] / "b").exists()
    assert any(e["kind"] == "失败" for e in engine.vault.logs())


def test_cancel_after_one_step(folders, engine):
    for name in ("a", "b", "c"):
        write(folders[0], name)
    event = Event()
    result = execute(engine, sync_plan(*snapshots(folders)), cancel=event,
                     progress=lambda *args: event.set())
    assert result.status == "cancelled" and result.completed == 1
    assert len(list(folders[1].iterdir())) == 1


def test_update_failure_preserves_existing_file(folders, engine, monkeypatch):
    write(folders[0], "x", "new")
    write(folders[1], "x", "old")
    monkeypatch.setattr(engine, "_stage", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    assert execute(engine, sync_plan(*snapshots(folders))).failed == 1
    assert (folders[1] / "x").read_text() == "old"


def test_hash_corruption_detected(folders, engine, monkeypatch):
    import folderpilot.engine as module
    write(folders[0], "x", "valid")
    real = module.fingerprint
    def corrupt(path, *args):
        entry = real(path, *args)
        return replace(entry, digest="bad") if path.name.startswith(".folderpilot-tmp-") else entry
    monkeypatch.setattr(module, "fingerprint", corrupt)
    result = execute(engine, sync_plan(*snapshots(folders)))
    assert result.failed == 1
    assert not list(folders[1].iterdir())


def test_quarantine_uses_verified_copy_before_unlink(folders, engine, monkeypatch):
    write(folders[0], "ref.txt")
    extra = write(folders[1], "extra.txt", "keep until verified")
    monkeypatch.setattr(engine, "_stage", lambda *args: (_ for _ in ()).throw(OSError("cross-volume copy failure")))
    result = execute(engine, cleanup_plan(*snapshots(folders), rule="name"))
    assert result.failed == 1 and extra.exists()


def test_interrupted_job_requires_review(folders, engine):
    write(folders[0], "file")
    engine._start("interrupted", "mirror")
    plan = sync_plan(*snapshots(folders))
    with pytest.raises(SafetyError, match="中断"):
        execute(engine, plan)
    with pytest.raises(SafetyError):
        engine.vault.review_interrupted("interrupted", confirmed=False)
    engine.vault.review_interrupted("interrupted", confirmed=True)
    assert execute(engine, plan).status == "completed"


def test_plan_cannot_replay(folders, engine):
    plan = sync_plan(*snapshots(folders))
    execute(engine, plan)
    with pytest.raises(SafetyError, match="已经执行过"):
        execute(engine, plan)


def test_changed_plan_token_rejected(folders, engine):
    plan = sync_plan(*snapshots(folders))
    changed = replace(plan, mode="mirror")
    with pytest.raises(SafetyError):
        engine.execute(changed, confirmation=token(plan))


def test_new_target_after_preview_is_not_overwritten(folders, engine):
    write(folders[0], "x")
    plan = sync_plan(*snapshots(folders))
    write(folders[1], "x", "arrived later")
    with pytest.raises(SafetyError):
        execute(engine, plan)
    assert (folders[1] / "x").read_text() == "arrived later"


def test_permanent_delete_double_confirmation(folders, engine):
    write(folders[0], "ref")
    write(folders[1], "extra")
    execute(engine, cleanup_plan(*snapshots(folders), rule="name"))
    item = engine.vault.items()[0]
    plan = engine.maintenance_plan(item["id"], "purge")
    with pytest.raises(SafetyError, match="二次确认"):
        engine.maintain(plan, confirmation=token(plan))
    assert engine.maintain(plan, confirmation=token(plan), permanent_confirmation="永久删除").completed == 1
    assert not Path(item["stored"]).exists()
    with pytest.raises(SafetyError):
        engine.maintenance_plan(item["id"])


def test_changed_restore_target_rejected(folders, engine):
    write(folders[0], "ref")
    write(folders[1], "extra")
    execute(engine, cleanup_plan(*snapshots(folders), rule="name"))
    item = engine.vault.items()[0]
    plan = engine.maintenance_plan(item["id"])
    write(folders[1], "extra", "new arrival")
    with pytest.raises(SafetyError, match="已变化"):
        engine.maintain(plan, confirmation=token(plan))


def test_vault_payload_corruption_blocks_restore(folders, engine):
    write(folders[0], "ref")
    write(folders[1], "extra")
    execute(engine, cleanup_plan(*snapshots(folders), rule="name"))
    item = engine.vault.items()[0]
    Path(item["stored"]).write_text("corrupted")
    with pytest.raises(SafetyError, match="完整性"):
        engine.maintenance_plan(item["id"])


def test_disk_space_failure_no_target_write(folders, engine, monkeypatch):
    import folderpilot.engine as module
    from collections import namedtuple
    write(folders[0], "x")
    usage = namedtuple("usage", "total used free")(1, 1, 0)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: usage)
    result = execute(engine, sync_plan(*snapshots(folders)))
    assert result.failed == 1 and not (folders[1] / "x").exists()


def test_skip_conflict(folders, engine):
    write(folders[0], "x", "new")
    write(folders[1], "x", "old")
    result = execute(engine, sync_plan(*snapshots(folders), conflict="skip"))
    assert result.skipped == 1 and (folders[1] / "x").read_text() == "old"
