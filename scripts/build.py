"""Build on Windows using an existing interpreter, without changing shell policy."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
temporary_root = root / ".local" / "build-temp"
temporary_root.mkdir(parents=True, exist_ok=True)
build_env = dict(os.environ, TEMP=str(temporary_root), TMP=str(temporary_root))
if sys.platform != "win32":
    raise SystemExit("Windows EXE 必须在 Windows 环境构建及验证")
subprocess.run([sys.executable, "-m", "pytest", "-q", "--junitxml=test-results.xml"], check=True)
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", "FolderPilot",
                "--version-file", "scripts/version_info.txt", "--manifest", "scripts/FolderPilot.manifest",
                "run_folderpilot.py"], check=True, env=build_env)
binary = root / "dist/FolderPilot.exe"
result_file = root / "dist/smoke-result.json"
subprocess.run([str(binary), "--smoke-test", str(result_file)], check=True, timeout=60, env=build_env)
result = json.loads(result_file.read_text(encoding="utf-8"))
if result["status"] != "passed":
    raise RuntimeError("EXE 自检失败")
for source, name in [("README.md", "README.md"), ("docs/USER_GUIDE.md", "USER_GUIDE.md"),
                     ("LICENSE", "LICENSE"), ("docs/RELEASE_NOTES.md", "RELEASE_NOTES.md")]:
    shutil.copy2(root / source, root / "dist" / name)
subprocess.run([sys.executable, "scripts/checksums.py"], check=True)
print("Build and actual EXE smoke test passed.")
