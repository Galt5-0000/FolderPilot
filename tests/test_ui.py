import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

from folderpilot.engine import token
from folderpilot.planning import sync_plan
from folderpilot.scan import scan
from folderpilot.storage import Vault
from folderpilot.engine import Engine
from folderpilot.ui import App
from conftest import write


@pytest.fixture(scope="module")
def shared_window(tmp_path_factory):
    value = App(tmp_path_factory.mktemp("ui") / "app-data")
    value.withdraw()
    yield value
    value.destroy()


@pytest.fixture
def app(shared_window, tmp_path):
    value = shared_window
    assert not value.busy
    value.plan, value.rows = None, []
    value.source.set("")
    value.target.set("")
    value.sync_mode.set("安全补全")
    value.data_root = tmp_path / "app-data"
    value.vault = Vault(value.data_root / "vault")
    value.engine = Engine(value.vault)
    value.show_page("首页")
    return value


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def wait_until(app, predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("后台任务未在预期时间完成")


def test_first_use_and_mode_explanation(app):
    app.show_page("文件夹同步")
    text = [str(w.cget("text")) for w in widgets(app.content) if isinstance(w, (ttk.Label, ttk.Button))]
    assert "安全补全保留目标独有文件；镜像同步会将它们移入隔离区。" in text
    assert "源文件夹（从这里复制）" in text
    assert "目标文件夹（更新到这里）" in text
    assert app.scan_button.cget("text") == "3. 查看待同步内容"
    assert str(app.scan_button.cget("state")) == "disabled"
    assert str(app.execute_button.cget("state")) == "disabled"
    title = next(w for w in widgets(app.content) if isinstance(w, ttk.Label) and w.cget("text") == "文件夹同步")
    assert not str(title.cget("font"))  # No option-database font overrides the title style.
    assert ttk.Style(app).lookup("Title.TLabel", "font") != "TkDefaultFont"


def test_read_only_page_has_no_execute_controls(app):
    app.show_page("差异检测")
    buttons = [str(w.cget("text")) for w in widgets(app.content) if isinstance(w, ttk.Button)]
    assert "确认同步…" not in buttons
    assert "查看完整计划" not in buttons


def test_changing_page_invalidates_sync_plan(app, folders):
    app.source.set(str(folders[0]))
    app.target.set(str(folders[1]))
    app.show_page("文件夹同步")
    app.plan = sync_plan(scan(folders[0]), scan(folders[1]))
    app.show_page("规则清理")
    assert app.plan is None
    assert str(app.execute_button.cget("state")) == "disabled"


def test_scan_runs_off_main_thread_and_enables_confirmation(app, folders, monkeypatch):
    import folderpilot.ui as module
    write(folders[0], "new.txt")
    app.source.set(str(folders[0]))
    app.target.set(str(folders[1]))
    app.show_page("文件夹同步")
    real_scan = module.scan
    thread_ids = []
    def checked_scan(*args, **kwargs):
        thread_ids.append(threading.get_ident())
        return real_scan(*args, **kwargs)
    monkeypatch.setattr(module, "scan", checked_scan)
    app.start_scan()
    assert app.busy
    assert str(app.scan_button.cget("state")) == "disabled"
    wait_until(app, lambda: not app.busy)
    assert app.plan is not None
    assert all(value != threading.get_ident() for value in thread_ids)
    assert str(app.execute_button.cget("state")) == "normal"
    assert str(app.preview_button.cget("state")) == "normal"
    assert not (folders[1] / "new.txt").exists()
    app.sync_mode.set("镜像同步")
    assert app.plan is None
    assert str(app.execute_button.cget("state")) == "disabled"


def test_deny_preview_never_modifies_files(app, folders, monkeypatch):
    write(folders[0], "new.txt")
    app.source.set(str(folders[0]))
    app.target.set(str(folders[1]))
    app.show_page("文件夹同步")
    app.plan = sync_plan(scan(folders[0]), scan(folders[1]))
    monkeypatch.setattr(app, "_preview_plan", lambda confirm: False)
    app.execute_plan()
    assert not app.busy
    assert not (folders[1] / "new.txt").exists()


def test_confirmed_sync_runs_in_worker(app, folders, monkeypatch):
    import folderpilot.ui as module
    write(folders[0], "new.txt", "test payload")
    app.source.set(str(folders[0]))
    app.target.set(str(folders[1]))
    app.show_page("文件夹同步")
    app.plan = sync_plan(scan(folders[0]), scan(folders[1]))
    monkeypatch.setattr(app, "_preview_plan", lambda confirm: True)
    monkeypatch.setattr(module.messagebox, "showinfo", lambda *args, **kwargs: None)
    app.execute_plan()
    wait_until(app, lambda: not app.busy)
    assert (folders[1] / "new.txt").read_text() == "test payload"
    assert app.plan is None


@pytest.mark.parametrize("dpi", [96, 144, 192])
def test_display_scaling_sizes_rows_and_sidebar(app, monkeypatch, dpi):
    import folderpilot.ui as module
    monkeypatch.setattr(module, "window_dpi", lambda _: dpi)
    app._refresh_display()
    assert app.scale == dpi / 96
    assert abs(float(app.tk.call("tk", "scaling")) - dpi / 72) < 0.02
    assert int(app.sidebar.cget("width")) == round(180 * dpi / 96)
    assert int(ttk.Style(app).lookup("Treeview", "rowheight")) == round(31 * dpi / 96)
