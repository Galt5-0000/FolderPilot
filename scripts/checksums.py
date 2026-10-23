"""Create reproducible SHA-256 release metadata."""
import hashlib
import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from folderpilot import __version__

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
binary = dist / "FolderPilot.exe"
if not binary.is_file() or binary.stat().st_size < 1_000_000:
    raise RuntimeError("Windows EXE 缺失或大小异常")
hasher = hashlib.sha256()
with binary.open("rb") as stream:
    while block := stream.read(1024 * 1024):
        hasher.update(block)
digest = hasher.hexdigest()
(dist / "SHA256SUMS.txt").write_text(f"{digest}  FolderPilot.exe\n", encoding="ascii")
(dist / "build-info.json").write_text(json.dumps({"version": __version__, "python": platform.python_version(),
    "platform": platform.platform(), "architecture": platform.machine(), "exe_bytes": binary.stat().st_size,
    "sha256": digest, "smoke_test": json.loads((dist / "smoke-result.json").read_text(encoding="utf-8"))}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"version": __version__, "exe_bytes": binary.stat().st_size, "sha256": digest}))
