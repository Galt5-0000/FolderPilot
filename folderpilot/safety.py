"""Path boundaries and link/reparse-point rejection."""
import os
import stat
from pathlib import Path
from .models import SafetyError

RESERVED = {".folderpilot-vault", ".folderpilot-tmp"}


def linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def safe_path(path: Path) -> Path:
    """Reject links in existing ancestors, including Windows junctions."""
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        if os.path.lexists(part) and linked(part):
            raise SafetyError(f"路径包含符号链接或联接点：{part}")
    return path


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def validate_roots(source: Path, target: Path, vault: Path | None = None) -> tuple[Path, Path]:
    source, target = safe_path(source), safe_path(target)
    for path in (source, target):
        if not path.is_dir():
            raise SafetyError(f"不是可访问目录：{path}")
        if path == Path(path.anchor):
            raise SafetyError("不能直接处理磁盘根目录")
        if (path / ".folderpilot-vault").exists():
            raise SafetyError("不能将隔离存储目录作为业务根目录")
    if inside(source, target) or inside(target, source):
        raise SafetyError("两个目录不能相同或相互嵌套")
    if vault is not None:
        vault = safe_path(vault)
        if any(inside(vault, p) or inside(p, vault) for p in (source, target)):
            raise SafetyError("隔离存储必须独立于两个业务目录")
    return source, target


def child(root: Path, relative: str) -> Path:
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts or not part.parts:
        raise SafetyError(f"非法相对路径：{relative}")
    result = safe_path(root / part)
    if not inside(result, root) or result == root:
        raise SafetyError("路径超出任务边界")
    return result
