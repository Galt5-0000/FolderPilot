"""Matching determines correspondence only; never reads file contents."""
from collections import defaultdict
from pathlib import PurePosixPath
from .models import Snapshot, SafetyError

RULES = {"name": "完整文件名", "stem": "文件名主体（忽略扩展名）",
         "path": "相对路径", "path_stem": "相对路径（忽略扩展名）"}


def match_key(relative: str, rule: str, case_sensitive: bool = False) -> str:
    path = PurePosixPath(relative)
    if rule == "name":
        value = path.name
    elif rule == "stem":
        value = path.stem
    elif rule == "path":
        value = path.as_posix()
    elif rule == "path_stem":
        value = path.with_suffix("").as_posix()
    else:
        raise SafetyError(f"未知匹配规则：{rule}")
    return value if case_sensitive else value.casefold()


def index(snapshot: Snapshot, rule: str, case_sensitive: bool = False) -> dict[str, list[str]]:
    result = defaultdict(list)
    for relative, entry in snapshot.entries.items():
        if entry.kind == "file":
            result[match_key(relative, rule, case_sensitive)].append(relative)
    return dict(result)
