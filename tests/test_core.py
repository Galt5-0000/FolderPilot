import os
from pathlib import Path
from threading import Event
import pytest
from folderpilot.compare import fingerprint, same_content
from folderpilot.matching import match_key
from folderpilot.models import Cancelled, Entry, SafetyError
from folderpilot.planning import cleanup_plan, diff, sync_plan
from folderpilot.scan import scan
from folderpilot.safety import child, validate_roots
from conftest import write, snapshots


def test_diff_categories(folders):
    a, b = folders
    write(a, "new.txt")
    write(b, "extra.txt", "extra content")
    write(a, "changed.txt", "AAA")
    write(b, "changed.txt", "BBB")
    write(a, "same.txt")
    write(b, "same.txt")
    assert {r.category for r in diff(*snapshots(folders))} == {"新增/目标缺失", "目标端独有", "修改", "未变化"}


def test_same_content_different_time(folders):
    a, b = (write(p, "same.txt") for p in folders)
    os.utime(b, ns=(1_000_000_000, 1_000_000_000))
    assert same_content(fingerprint(a), fingerprint(b))
    assert not same_content(fingerprint(a), fingerprint(b), "quick")
    assert sync_plan(*snapshots(folders)).operations[0].action == "skip"


def test_same_name_different_hash_matches_stem(folders):
    a, b = folders
    write(a, "file.docx", "reference")
    write(b, "file.pdf", "different bytes and size")
    plan = cleanup_plan(*snapshots(folders), rule="stem")
    assert plan.operations[0].action == "skip"
    assert fingerprint(a / "file.docx").digest != fingerprint(b / "file.pdf").digest


@pytest.mark.parametrize("rule,left,right,equal", [
    ("name", "a/file.txt", "b/file.txt", True),
    ("stem", "a/file.txt", "b/file.csv", True),
    ("path", "a/file.txt", "b/file.txt", False),
    ("path_stem", "a/file.txt", "a/file.csv", True),
    ("path_stem", "a/file.txt", "b/file.csv", False),
    ("name", "报告.TXT", "报告.txt", True),
])
def test_matching_rules(rule, left, right, equal):
    assert (match_key(left, rule) == match_key(right, rule)) is equal


def test_case_sensitive(folders):
    write(folders[0], "Report.doc")
    write(folders[1], "report.pdf")
    assert cleanup_plan(*snapshots(folders), rule="stem").operations[0].action == "skip"
    assert cleanup_plan(*snapshots(folders), rule="stem", case_sensitive=True).operations[0].action == "quarantine"


def test_duplicates_block_cleanup_but_path_rule_resolves(folders):
    for p in folders:
        write(p, "a/item.txt")
        write(p, "b/item.txt")
    with pytest.raises(SafetyError, match="歧义"):
        cleanup_plan(*snapshots(folders), rule="name")
    assert all(o.action == "skip" for o in cleanup_plan(*snapshots(folders), rule="path").operations)
    assert any(r.category == "重复文件名" for r in diff(*snapshots(folders)))


def test_empty_reference_blocked(folders):
    write(folders[1], "valuable.txt")
    with pytest.raises(SafetyError, match="参考目录为空"):
        cleanup_plan(*snapshots(folders))


def test_empty_directories_and_move_hint(folders):
    a, b = folders
    (a / "empty" / "nested").mkdir(parents=True)
    write(a, "new/location.txt")
    write(b, "old/location.txt")
    report = diff(*snapshots(folders))
    assert sum(r.category == "目录差异" for r in report) == 4
    assert any(r.category == "移动/重命名线索" for r in report)
    assert not any(o.action == "rename" for o in sync_plan(*snapshots(folders)).operations)


def test_extensions_and_nonrecursive(folders):
    a, b = folders
    write(a, "keep.txt")
    write(b, "keep.csv")
    write(b, "ignored.bin")
    write(b, "deep/remove.csv")
    refs = scan(a, recursive=False, extensions=("TXT",))
    targets = scan(b, recursive=False, extensions=("*.csv",))
    assert set(targets.entries) == {"keep.csv", "deep"}
    assert cleanup_plan(refs, targets).operations[0].action == "skip"


def test_scan_access_error_blocks_mutations(folders, monkeypatch):
    import folderpilot.scan as module
    real = module.fingerprint
    write(folders[0], "denied.txt")
    def denied(path, *args):
        if path.name == "denied.txt":
            raise PermissionError("模拟访问被拒绝")
        return real(path, *args)
    monkeypatch.setattr(module, "fingerprint", denied)
    snapshots_ = snapshots(folders)
    assert snapshots_[0].errors
    with pytest.raises(SafetyError, match="扫描不完整"):
        sync_plan(*snapshots_)


def test_nested_same_invalid_roots(folders):
    a, b = folders
    with pytest.raises(SafetyError):
        validate_roots(a, a)
    nested = a / "nested"
    nested.mkdir()
    with pytest.raises(SafetyError):
        validate_roots(a, nested)
    with pytest.raises(SafetyError):
        validate_roots(a, b / "not-found")
    with pytest.raises(SafetyError):
        validate_roots(a, b, a / "vault")
    with pytest.raises(SafetyError):
        child(b, "../outside")


def test_quarantine_excluded(folders):
    a = folders[0]
    write(a, ".folderpilot-vault/secret.txt")
    write(a, "vault/.folderpilot-vault", "")
    write(a, "vault/objects/secret.txt")
    write(a, "normal.txt")
    assert set(scan(a).entries) == {"normal.txt"}


def test_unfinished_temporary_blocks_scan(folders):
    write(folders[0], ".folderpilot-tmp-abandoned")
    assert scan(folders[0]).errors


def test_symlink_rejected(folders, monkeypatch):
    # Exercise link branch deterministically without requiring Windows symlink privilege.
    import folderpilot.scan as module
    write(folders[0], "link.txt")
    real = module.linked
    monkeypatch.setattr(module, "linked", lambda p: p.name == "link.txt" or real(p))
    assert "联接点" in scan(folders[0]).errors[0]


def test_scan_cancel(folders):
    event = Event()
    event.set()
    with pytest.raises(Cancelled):
        scan(folders[0], cancel=event)


def test_quick_snapshots_cannot_be_executed(folders):
    write(folders[0], "x")
    with pytest.raises(SafetyError, match="精确扫描"):
        sync_plan(*snapshots(folders, exact=False))


def test_type_conflict(folders):
    write(folders[0], "x")
    (folders[1] / "x").mkdir()
    assert diff(*snapshots(folders))[0].category == "歧义"
    with pytest.raises(SafetyError, match="类型冲突"):
        sync_plan(*snapshots(folders))
