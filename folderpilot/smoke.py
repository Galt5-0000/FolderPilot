"""A real frozen-app diagnostic using generated data only."""
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from . import __version__
from .engine import Engine, token
from .planning import cleanup_plan, sync_plan
from .scan import scan
from .storage import Vault


def smoke_test(output: Path, gui: bool = True) -> None:
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"version": __version__, "status": "running", "checks": []}
    try:
        with tempfile.TemporaryDirectory(prefix="folderpilot-smoke-", dir=output.parent) as folder:
            root = Path(folder)
            source, target = root / "主目录", root / "副目录"
            source.mkdir()
            target.mkdir()
            (source / "empty").mkdir()
            (source / "报告.txt").write_text("新内容", encoding="utf-8")
            (target / "报告.txt").write_text("旧内容", encoding="utf-8")
            (target / "多余.bin").write_bytes(b"extra")
            engine = Engine(Vault(root / "vault"))
            plan = sync_plan(scan(source), scan(target))
            outcome = engine.execute(plan, confirmation=token(plan))
            assert outcome.status == "completed", asdict(outcome)
            assert (target / "报告.txt").read_text(encoding="utf-8") == "新内容"
            assert (target / "多余.bin").exists()
            assert (target / "empty").is_dir()
            report["checks"].append("安全补全、中文路径、覆盖旧版隔离、保留独有文件、空目录")
            cleanup = cleanup_plan(scan(source), scan(target), rule="stem")
            assert engine.execute(cleanup, confirmation=token(cleanup)).status == "completed"
            item = next(i for i in engine.vault.items() if i["kind"] == "cleanup")
            restore = engine.maintenance_plan(item["id"])
            assert engine.maintain(restore, confirmation=token(restore)).status == "completed"
            assert (target / "多余.bin").read_bytes() == b"extra"
            report["checks"].append("规则清理、校验隔离副本、恢复")
            if gui:
                from .ui import App
                app = App(root / "app-data")
                try:
                    for page in ("首页", "差异检测", "文件夹同步", "规则清理", "隔离与恢复", "任务管理", "日志与设置"):
                        app.show_page(page)
                        app.update()
                        assert app.winfo_exists()
                    report["checks"].append("Tk 中文主窗口与七个导航页面实际创建、布局、刷新")
                    report["display"] = {"window_dpi": app.dpi, "tk_scaling": float(app.tk.call("tk", "scaling")),
                                         "sidebar_width": int(app.sidebar.cget("width"))}
                    import sys
                    if sys.platform == "win32":
                        import ctypes
                        user32 = ctypes.windll.user32
                        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
                        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
                        awareness = user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext())
                        assert awareness == 2, f"Expected per-monitor DPI awareness; got {awareness}"
                        report["display"]["dpi_awareness"] = "per-monitor"
                finally:
                    app.destroy()
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
