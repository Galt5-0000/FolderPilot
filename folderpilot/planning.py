"""Read-only reports and immutable, self-contained operation previews."""
from collections import Counter, defaultdict
from pathlib import Path
from threading import Event
from uuid import uuid4
from .compare import same_content
from .matching import index, match_key
from .models import Operation, Plan, Row, SafetyError, Snapshot
from .safety import child, validate_roots
from .scan import scan


def diff(source: Snapshot, target: Snapshot, mode: str = "exact") -> list[Row]:
    rows = []
    for relative in sorted(source.entries.keys() | target.entries.keys()):
        left, right = source.entries.get(relative), target.entries.get(relative)
        src, dst = str(source.root / relative), str(target.root / relative)
        if left and right and left.kind != right.kind:
            rows.append(Row("歧义", relative, src, dst, "同一路径的文件与目录类型冲突"))
        elif (left or right).kind == "dir":
            if not left or not right:
                rows.append(Row("目录差异", relative, src if left else "", dst if right else "", "仅主目录存在" if left else "仅目标目录存在"))
        elif not right:
            rows.append(Row("新增/目标缺失", relative, src, dst, "按相对路径对应；目标缺失"))
        elif not left:
            rows.append(Row("目标端独有", relative, "", dst, "主目录中无此相对路径"))
        else:
            equal = same_content(left, right, mode)
            rows.append(Row("未变化" if equal else "修改", relative, src, dst,
                            ("SHA-256 一致" if equal else "内容不同") if mode == "exact" else "快速模式仅比较大小及时间；不证明内容一致"))
    # Content hints are advisory, never rename instructions.
    added, removed = defaultdict(list), defaultdict(list)
    for rel, entry in source.entries.items():
        if entry.digest and rel not in target.entries:
            added[entry.digest].append(rel)
    for rel, entry in target.entries.items():
        if entry.digest and rel not in source.entries:
            removed[entry.digest].append(rel)
    for digest in added.keys() & removed.keys():
        rows.append(Row("移动/重命名线索", ", ".join(added[digest]), str(source.root), str(target.root),
                        f"内容相同的新增路径 {added[digest]} / 旧路径 {removed[digest]}；不自动重命名"))
    for snap in (source, target):
        names = Counter(Path(p).name.casefold() for p, e in snap.entries.items() if e.kind == "file")
        for name, count in names.items():
            if count > 1:
                rows.append(Row("重复文件名", name, str(snap.root), "", f"共 {count} 项；相对路径仍独立对应"))
        for error in snap.errors:
            rows.append(Row("错误", "", str(snap.root), "", error))
    return rows


def _ready(source: Snapshot, target: Snapshot) -> None:
    validate_roots(source.root, target.root)
    if source.errors or target.errors:
        raise SafetyError("扫描不完整，禁止执行：\n" + "\n".join(source.errors + target.errors))
    for snap in (source, target):
        folded = [p.casefold() for p in snap.entries]
        if len(folded) != len(set(folded)):
            raise SafetyError("存在 Windows 大小写路径碰撞")
        if any(e.kind == "file" and not e.digest for e in snap.entries.values()):
            raise SafetyError("执行计划必须先使用精确扫描建立校验基线")
    left = {p.casefold(): p for p in source.entries}
    for p in target.entries:
        if p.casefold() in left and left[p.casefold()] != p:
            raise SafetyError("两端相对路径大小写不同，请先手动统一后重新扫描")


def sync_plan(source: Snapshot, target: Snapshot, *, mirror: bool = False,
              conflict: str = "update") -> Plan:
    _ready(source, target)
    if not source.recursive or not target.recursive or source.extensions or target.extensions:
        raise SafetyError("同步需要递归、无扩展名过滤的完整扫描")
    if conflict not in {"update", "skip"}:
        raise SafetyError("未知冲突策略")
    operations = []
    for rel in sorted(source.entries, key=lambda p: (p.count("/"), p)):
        entry, previous = source.entries[rel], target.entries.get(rel)
        src, dst = str(child(source.root, rel)), str(child(target.root, rel))
        if previous and previous.kind != entry.kind:
            raise SafetyError(f"文件/目录类型冲突，需先手动处理：{rel}")
        if entry.kind == "dir":
            if not previous:
                operations.append(Operation("mkdir", rel, src, dst, "补全目录结构"))
        elif not previous:
            operations.append(Operation("copy", rel, src, dst, "目标缺失"))
        elif same_content(entry, previous):
            operations.append(Operation("skip", rel, src, dst, "内容一致"))
        else:
            operations.append(Operation("update" if conflict == "update" else "skip", rel, src, dst,
                                        "覆盖前保存旧版本" if conflict == "update" else "用户选择跳过冲突"))
    if mirror:
        extras = set(target.entries) - set(source.entries)
        for rel in sorted(extras, key=lambda p: (-p.count("/"), p)):
            action = "quarantine" if target.entries[rel].kind == "file" else "rmdir"
            operations.append(Operation(action, rel, "", str(child(target.root, rel)), "镜像清理目标端独有项（目录仅在空时移除并保留恢复记录）"))
    return Plan(uuid4().hex, "mirror" if mirror else "complete", source, target, tuple(operations))


def cleanup_plan(source: Snapshot, target: Snapshot, *, rule: str = "stem",
                 case_sensitive: bool = False) -> Plan:
    _ready(source, target)
    refs, targets = index(source, rule, case_sensitive), index(target, rule, case_sensitive)
    if not refs:
        raise SafetyError("参考目录为空或过滤后没有文件，禁止清理")
    collisions = [f"{key}: 参考 {refs.get(key, [])} / 目标 {targets.get(key, [])}"
                  for key in refs.keys() | targets.keys()
                  if len(refs.get(key, [])) > 1 or len(targets.get(key, [])) > 1]
    if collisions:
        raise SafetyError("匹配歧义，请缩小范围或改用相对路径规则：\n" + "\n".join(collisions))
    operations = []
    for rel, entry in sorted(target.entries.items()):
        if entry.kind != "file":
            continue
        key = match_key(rel, rule, case_sensitive)
        operations.append(Operation("skip" if key in refs else "quarantine", rel, "", str(child(target.root, rel)),
                                    f"规则 {rule}；匹配键 {key}；" + ("存在对应项，内容不参与匹配" if key in refs else "参考端无对应项")))
    return Plan(uuid4().hex, "cleanup", source, target, tuple(operations))


def revalidate(snapshot: Snapshot, cancel: Event | None = None) -> None:
    fresh = scan(snapshot.root, exact=True, recursive=snapshot.recursive,
                 extensions=snapshot.extensions, cancel=cancel)
    if fresh.errors or fresh.entries != snapshot.entries:
        raise SafetyError(f"扫描后目录内容发生变化或不可访问，请重新生成计划：{snapshot.root}")
