"""Read-only scanning. Incomplete scans are never safe mutation inputs."""
import os
from pathlib import Path
from threading import Event
from .compare import fingerprint
from .models import Cancelled, Progress, Snapshot, checkpoint
from .safety import RESERVED, safe_path, linked, inside


def normalize_extensions(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({"." + item.strip().lstrip("*.").casefold() for item in values if item.strip().lstrip("*.")}))


def scan(root: Path, *, exact: bool = True, recursive: bool = True,
         extensions: tuple[str, ...] = (), exclude: tuple[Path, ...] = (),
         cancel: Event | None = None, progress: Progress | None = None) -> Snapshot:
    root = safe_path(root)
    entries, errors = {}, []
    extensions = normalize_extensions(extensions)

    def visit(directory: Path) -> None:
        checkpoint(cancel)
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda e: e.name.casefold())
            for item in children:
                checkpoint(cancel)
                path = Path(item.path)
                if item.name in RESERVED or any(inside(path, p) for p in exclude):
                    continue
                if item.name.startswith(".folderpilot-tmp-"):
                    errors.append(f"发现未完成的临时副本，请先检查：{path}")
                    continue
                try:
                    if linked(path):
                        raise OSError("不扫描符号链接或联接点")
                    is_dir = item.is_dir(follow_symlinks=False)
                    if is_dir and (path / ".folderpilot-vault").exists():
                        continue
                    if not is_dir and extensions and path.suffix.casefold() not in extensions:
                        continue
                    entries[path.relative_to(root).as_posix()] = fingerprint(path, exact, cancel)
                    if progress:
                        progress(str(path), len(entries), 0)
                    if is_dir and recursive:
                        visit(path)
                except Cancelled:
                    raise
                except (OSError, RuntimeError) as exc:
                    errors.append(f"{path}: {type(exc).__name__}: {exc}")
        except Cancelled:
            raise
        except OSError as exc:
            errors.append(f"{directory}: {type(exc).__name__}: {exc}")

    visit(root)
    return Snapshot(root, entries, tuple(errors), recursive, extensions)
