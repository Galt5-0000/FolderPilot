"""Chinese Tk interface. Workers communicate only through a queue."""
import csv
import json
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from uuid import uuid4
from . import __version__
from .config import TaskConfig
from .display import enable_dpi_awareness, window_dpi
from .engine import Engine, MaintenancePlan, token
from .matching import RULES
from .models import Cancelled, Outcome, Row, SafetyError
from .planning import cleanup_plan, diff, sync_plan
from .safety import validate_roots
from .scan import scan
from .storage import Vault

ACTION_LABELS = {"copy": "复制", "update": "更新并保存旧版本", "skip": "跳过", "mkdir": "创建目录",
                 "quarantine": "移入隔离区", "rmdir": "移除空目录并记录", "restore": "恢复", "purge": "永久删除"}
STATUS_LABELS = {"ready": "可恢复", "preparing": "未完成（需核查）", "restored": "已恢复（副本保留）",
                 "purged": "已永久删除"}


def default_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return base / "FolderPilot"


class App(tk.Tk):
    def __init__(self, data_root: Path | None = None):
        enable_dpi_awareness()
        super().__init__()
        self.title(f"FolderPilot {__version__} · 文件夹差异与安全管理")
        self.dpi = window_dpi(self)
        self.scale = self.dpi / 96
        self.tk.call("tk", "scaling", self.dpi / 72)
        self._size_window(self, 1220, 820)
        self.data_root = data_root or default_data_dir()
        self.vault = Vault(self.data_root / "vault")
        self.engine = Engine(self.vault)
        self.tasks_dir = self.data_root / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.messages = queue.SimpleQueue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.closing = False
        self.current_page = "首页"
        self.plan = None
        self.rows = []
        self.disabled_controls = []
        self.source = tk.StringVar()
        self.target = tk.StringVar()
        self.rule = tk.StringVar(value=RULES["stem"])
        self.compare_mode = tk.StringVar(value="精确比较（SHA-256）")
        self.sync_mode = tk.StringVar(value="安全补全")
        self.conflict = tk.StringVar(value="更新并隔离旧版本")
        self.extensions = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.case_sensitive = tk.BooleanVar(value=False)
        self.filter_value = tk.StringVar(value="全部")
        self.vault_query = tk.StringVar()
        self.status = tk.StringVar(value="选择左侧功能开始")
        self._style()
        self._layout()
        for variable in (self.source, self.target, self.rule, self.compare_mode, self.sync_mode,
                         self.conflict, self.extensions, self.recursive, self.case_sensitive):
            variable.trace_add("write", self._invalidate)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.show_page("首页")
        self.after(100, self._poll)

    def px(self, value: int) -> int:
        return max(1, round(value * self.scale))

    def _size_window(self, window, width, height):
        available_w = max(640, self.winfo_screenwidth() - self.px(50))
        available_h = max(480, self.winfo_screenheight() - self.px(85))
        window.geometry(f"{min(self.px(width), available_w)}x{min(self.px(height), available_h)}")
        window.minsize(min(self.px(960), available_w), min(self.px(640), available_h))

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            tkfont.nametofont(name).configure(family="Microsoft YaHei UI", size=10)
        style.configure("TFrame", background="#f3f6fb")
        style.configure("TLabel", background="#f3f6fb", foreground="#24334a", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"), foreground="#162945")
        style.configure("Subtitle.TLabel", foreground="#62718a")
        style.configure("TButton", padding=(13, 8), font=("Microsoft YaHei UI", 10))
        style.configure("Primary.TButton", background="#2469c9", foreground="white")
        style.map("Primary.TButton", background=[("active", "#1857ae"), ("disabled", "#b5c6dd")])
        style.configure("Treeview", rowheight=self.px(31), font=("Microsoft YaHei UI", 10), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=7)
        style.configure("TLabelframe", background="#f3f6fb")
        style.configure("TLabelframe.Label", background="#f3f6fb", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TCheckbutton", font=("Microsoft YaHei UI", 10))
        style.configure("TCombobox", font=("Microsoft YaHei UI", 10))
        style.configure("TEntry", font=("Microsoft YaHei UI", 10))

    def _layout(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = self.sidebar = tk.Frame(self, bg="#162945", width=self.px(180))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text="FolderPilot", fg="white", bg="#162945", font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=self.px(16), pady=(25, 3))
        tk.Label(sidebar, text=f"v{__version__}", fg="#aac3e3", bg="#162945", font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=20, pady=(0, 30))
        self.nav_buttons = []
        for page in ("首页", "差异检测", "文件夹同步", "规则清理", "隔离与恢复", "任务管理", "日志与设置"):
            button = tk.Button(sidebar, text=page, anchor="w", bg="#162945", fg="#e2ebf7", activebackground="#294b77", activeforeground="white",
                               relief="flat", borderwidth=0, padx=22, pady=13, command=lambda p=page: self.show_page(p), cursor="hand2")
            button.pack(fill="x", padx=8, pady=2)
            self.nav_buttons.append(button)
        self.content = ttk.Frame(self, padding=(28, 22))
        self.content.grid(row=0, column=1, sticky="nsew")
        bottom = ttk.Frame(self, padding=(15, 8))
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bottom, length=self.px(120), mode="determinate")
        self.progress.grid(row=0, column=1, padx=12)
        self.cancel_button = ttk.Button(bottom, text="取消任务", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=2)

    def _invalidate(self, *_):
        self.plan = None
        self._refresh_actions()
        if self.rows and not self.busy:
            self.status.set("设置已更改，请重新扫描。")

    def _refresh_actions(self):
        if hasattr(self, "execute_button") and self.execute_button.winfo_exists():
            self.execute_button.configure(state="normal" if self.plan and not self.busy else "disabled")
        if hasattr(self, "preview_button") and self.preview_button.winfo_exists():
            self.preview_button.configure(state="normal" if self.plan and not self.busy else "disabled")
        if hasattr(self, "scan_button") and self.scan_button.winfo_exists():
            self.scan_button.configure(state="normal" if self.source.get().strip() and self.target.get().strip() and not self.busy else "disabled")

    def show_page(self, page: str):
        if self.busy:
            return
        if page != self.current_page:
            self.plan = None
            self.rows = []
            self.filter_value.set("全部")
        self.current_page = page
        for button in self.nav_buttons:
            button.configure(bg="#294b77" if button.cget("text") == page else "#162945")
        for widget in self.content.winfo_children():
            widget.destroy()
        self.content.columnconfigure(0, weight=1)
        for i in range(12):
            self.content.rowconfigure(i, weight=0)
        ttk.Label(self.content, text=page, style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        if page == "首页":
            self._home()
        elif page in {"差异检测", "文件夹同步", "规则清理"}:
            self._workspace(page)
        elif page == "隔离与恢复":
            self._quarantine_page()
        elif page == "任务管理":
            self._tasks_page()
        else:
            self._logs_page()

    def _home(self):
        ttk.Label(self.content, text="选择功能 → 选择两个文件夹 → 扫描后确认处理", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 26))
        cards = ttk.Frame(self.content)
        cards.grid(row=2, column=0, sticky="ew")
        for i, (title, body, page) in enumerate([
            ("查看哪里不一样", "比较两个文件夹，\n不修改任何文件。", "差异检测"),
            ("补全或更新文件夹", "将源文件夹的内容\n复制到目标文件夹。", "文件夹同步"),
            ("清理多余文件", "以参考文件夹为名单，\n移走另一边多出的文件。", "规则清理"),
        ]):
            cards.columnconfigure(i, weight=1)
            card = ttk.LabelFrame(cards, text=title, padding=18)
            card.grid(row=0, column=i, sticky="nsew", padx=(0, 15 if i < 2 else 0))
            ttk.Label(card, text=body, justify="left").pack(anchor="w")
            ttk.Button(card, text="开始 →", command=lambda p=page: self.show_page(p)).pack(anchor="w", pady=(16, 0))
        ttk.Label(self.content, text="被替换和清理的文件会保存在“隔离与恢复”中，方便找回。", padding=(0, 24)).grid(row=3, column=0, sticky="w")
        pending = self.vault.jobs(pending=True)
        if pending:
            ttk.Label(self.content, text=f"发现 {len(pending)} 个未完成任务，请先到“隔离与恢复”核查。", foreground="#b24224").grid(row=5, column=0, sticky="w", pady=15)

    def _path_row(self, frame, row, title, variable):
        ttk.Label(frame, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Button(frame, text="选择文件夹", command=lambda: self._choose(variable)).grid(row=row, column=2, padx=(8, 0), pady=5)

    def _choose(self, variable):
        value = filedialog.askdirectory(parent=self, mustexist=True)
        if value:
            variable.set(value)

    def _workspace(self, page):
        subtitles = {"差异检测": "查看两个文件夹有哪些不同，不会修改文件。",
                     "文件夹同步": "安全补全保留目标独有文件；镜像同步会将它们移入隔离区。",
                     "规则清理": "以参考文件夹为保留名单，找出另一边多余的文件。"}
        ttk.Label(self.content, text=subtitles[page], style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 15))
        paths = ttk.LabelFrame(self.content, text="1. 选择文件夹", padding=(15, 10))
        paths.grid(row=2, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        labels = {"差异检测": ("文件夹 A", "文件夹 B"),
                  "文件夹同步": ("源文件夹（从这里复制）", "目标文件夹（更新到这里）"),
                  "规则清理": ("参考文件夹（保留名单）", "待清理文件夹")}
        self._path_row(paths, 0, labels[page][0], self.source)
        self._path_row(paths, 1, labels[page][1], self.target)
        options = ttk.LabelFrame(self.content, text="2. 选择处理方式", padding=(15, 10))
        options.grid(row=3, column=0, sticky="ew", pady=12)
        if page == "文件夹同步":
            ttk.Label(options, text="同步模式").grid(row=0, column=0, padx=(0, 8))
            ttk.Combobox(options, textvariable=self.sync_mode, values=("安全补全", "镜像同步"), state="readonly", width=14).grid(row=0, column=1, padx=(0, 18))
            ttk.Label(options, text="同路径文件内容不同").grid(row=0, column=2, padx=(0, 8))
            ttk.Combobox(options, textvariable=self.conflict, values=("更新并隔离旧版本", "跳过冲突"), state="readonly", width=20).grid(row=0, column=3)
        elif page == "规则清理":
            ttk.Label(options, text="匹配规则").grid(row=0, column=0, padx=(0, 8))
            ttk.Combobox(options, textvariable=self.rule, values=list(RULES.values()), state="readonly", width=30).grid(row=0, column=1, padx=(0, 15))
            ttk.Checkbutton(options, text="区分大小写", variable=self.case_sensitive).grid(row=0, column=2)
            ttk.Checkbutton(options, text="递归子目录", variable=self.recursive).grid(row=0, column=3, padx=12)
            ttk.Label(options, text="扩展名（逗号分隔，留空为全部）").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Entry(options, textvariable=self.extensions, width=30).grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Label(options, text="例如：报告.docx 与 报告.pdf，选“文件名主体”即可匹配。", style="Subtitle.TLabel").grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        else:
            ttk.Label(options, text="内容比较").grid(row=0, column=0, padx=(0, 8))
            ttk.Combobox(options, textvariable=self.compare_mode, values=("精确比较（SHA-256）", "快速比较（大小与时间）"), state="readonly", width=28).grid(row=0, column=1, padx=(0, 12))
            ttk.Checkbutton(options, text="递归子目录", variable=self.recursive).grid(row=0, column=2)
            ttk.Label(options, text="快速比较只作初步判断，不能证明内容一致。", style="Subtitle.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        actions = ttk.Frame(self.content)
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        scan_labels = {"差异检测": "3. 扫描差异", "文件夹同步": "3. 查看待同步内容", "规则清理": "3. 查找多余文件"}
        self.scan_button = ttk.Button(actions, text=scan_labels[page], style="Primary.TButton", command=self.start_scan)
        self.scan_button.pack(side="left")
        if page != "差异检测":
            self.preview_button = ttk.Button(actions, text="查看完整计划", command=lambda: self._preview_plan(False))
            self.preview_button.pack(side="left", padx=8)
            self.execute_button = ttk.Button(actions, text="确认同步…" if page == "文件夹同步" else "确认清理…", command=self.execute_plan)
            self.execute_button.pack(side="left")
        ttk.Button(actions, text="导出报告", command=self.export_report).pack(side="left", padx=8)
        self.filter_box = ttk.Combobox(actions, textvariable=self.filter_value, state="readonly", width=18)
        self.filter_box.pack(side="right")
        self.filter_box.bind("<<ComboboxSelected>>", lambda _: self._fill_rows())
        self.summary = ttk.Label(self.content, text="尚未扫描", style="Subtitle.TLabel")
        self.summary.grid(row=5, column=0, sticky="w", pady=(0, 8))
        self.table = self._table(self.content, 6, ("分类", "相对路径", "主目录完整路径", "目标完整路径", "依据 / 原因"), (110, 170, 250, 250, 350))
        self.table.bind("<Double-1>", self._row_detail)
        self._fill_rows()
        self._refresh_actions()

    def _table(self, parent, row, columns, widths):
        parent.rowconfigure(row, weight=1)
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        tree = ttk.Treeview(box, columns=columns, show="headings", selectmode="browse")
        for name, width in zip(columns, widths):
            tree.heading(name, text=name)
            tree.column(name, width=self.px(width), minwidth=self.px(80), stretch=False)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(box, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return tree

    def config(self) -> TaskConfig:
        return TaskConfig(source=self.source.get().strip(), target=self.target.get().strip(), recursive=self.recursive.get(),
                          rule=next(k for k, v in RULES.items() if v == self.rule.get()), case_sensitive=self.case_sensitive.get(),
                          extensions=tuple(x.strip() for x in self.extensions.get().replace("，", ",").split(",") if x.strip()),
                          compare_mode="quick" if self.compare_mode.get().startswith("快速") else "exact",
                          sync_mode="mirror" if self.sync_mode.get() == "镜像同步" else "complete",
                          conflict="skip" if self.conflict.get() == "跳过冲突" else "update")

    def start_scan(self):
        if self.busy:
            return
        config, page = self.config(), self.current_page
        if not config.source or not config.target:
            messagebox.showerror("目录未设置", "请选择两个文件夹。", parent=self)
            return
        self.plan = None
        self._refresh_actions()
        signature = asdict(config)
        def worker():
            a, b = validate_roots(Path(config.source), Path(config.target), self.vault.root)
            task_id = uuid4().hex
            self.vault.event(task_id, "扫描开始", json.dumps(signature, ensure_ascii=False))
            exact = config.compare_mode == "exact" or page != "差异检测"
            options = {"exact": exact, "recursive": config.recursive if page != "文件夹同步" else True,
                       "extensions": config.extensions if page == "规则清理" else (),
                       "cancel": self.cancel_event, "progress": self._progress}
            try:
                source, target = scan(a, **options), scan(b, **options)
                rows = diff(source, target, "exact" if exact else "quick")
                plan = None
                if page != "差异检测":
                    try:
                        plan = (cleanup_plan(source, target, rule=config.rule, case_sensitive=config.case_sensitive)
                                if page == "规则清理" else sync_plan(source, target, mirror=config.sync_mode == "mirror", conflict=config.conflict))
                        rows = [Row(ACTION_LABELS[o.action], o.relative, o.source, o.target, o.reason) for o in plan.operations]
                    except SafetyError as exc:
                        rows.append(Row("阻止执行", "", str(a), str(b), str(exc)))
                self.vault.event(task_id, "扫描结束", f"主目录 {len(source.entries)}；目标 {len(target.entries)}；报告 {len(rows)}；错误 {len(source.errors) + len(target.errors)}")
                return rows, plan
            except Exception as exc:
                self.vault.event(task_id, "扫描取消" if isinstance(exc, Cancelled) else "扫描失败", f"{type(exc).__name__}: {exc}")
                raise
        def done(value):
            if asdict(self.config()) != signature:
                self.status.set("扫描期间配置已更改，请重新扫描。")
                return
            self.rows, self.plan = value
            self.filter_value.set("全部")
            self._fill_rows()
            self._refresh_actions()
            self.status.set(f"扫描完成 · {len(self.rows)} 条报告；" + ("可预览执行" if self.plan else "只读报告"))
        self._run(worker, done, "正在扫描与校验…")

    def _fill_rows(self):
        if not hasattr(self, "table") or not self.table.winfo_exists():
            return
        self.table.delete(*self.table.get_children())
        categories = Counter(row.category for row in self.rows)
        self.filter_box.configure(values=["全部", *sorted(categories)])
        for i, row in enumerate(self.rows):
            if self.filter_value.get() in {"全部", row.category}:
                self.table.insert("", "end", iid=str(i), values=(row.category, row.relative, row.source, row.target, row.reason))
        self.summary.configure(text=(f"共 {len(self.rows)} 项  ·  " + "  /  ".join(f"{k} {v}" for k, v in categories.items()))
                               if self.rows else "选择两个文件夹后，点击上方第 3 步查看结果。")

    def _row_detail(self, _=None):
        selection = self.table.selection()
        if selection:
            row = self.rows[int(selection[0])]
            self._text_dialog("文件详情", "\n\n".join(f"{k}：{v}" for k, v in zip(("分类", "相对路径", "主目录", "目标", "原因"), asdict(row).values())))

    def _text_dialog(self, title: str, body: str, confirm: bool = False) -> bool:
        window = tk.Toplevel(self)
        window.title(title)
        self._size_window(window, 960, 600)
        window.transient(self)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10), padx=12, pady=12)
        scroll = ttk.Scrollbar(frame, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", body)
        text.configure(state="disabled")
        accepted = [False]
        def approve():
            accepted[0] = True
            window.destroy()
        footer = ttk.Frame(window, padding=12)
        footer.pack(fill="x")
        ttk.Button(footer, text="确认并执行" if confirm else "关闭", command=approve, style="Primary.TButton").pack(side="right")
        if confirm:
            ttk.Button(footer, text="取消", command=window.destroy).pack(side="right", padx=8)
        window.grab_set()
        self.wait_window(window)
        return accepted[0]

    def _preview_plan(self, confirm=False):
        if not self.plan:
            messagebox.showinfo("尚无可执行计划", "请先扫描并解决报告中的阻止执行项。", parent=self)
            return False
        plan = self.plan
        counts = Counter(ACTION_LABELS[o.action] for o in plan.operations)
        mode = {"complete": "安全补全", "mirror": "镜像同步", "cleanup": "规则清理"}[plan.mode]
        body = (f"模式：{mode}\n源 / 参考文件夹：{plan.source.root}\n目标文件夹：{plan.target.root}\n"
                f"共 {len(plan.operations)} 项：" + "，".join(f"{label} {count}" for label, count in counts.items()) + "\n\n"
                "被替换或清理的文件可在“隔离与恢复”中找回。\n\n")
        body += "\n\n".join(f"[{i+1}] {ACTION_LABELS[o.action]}\n源：{o.source or '—'}\n目标：{o.target}\n依据：{o.reason}" for i, o in enumerate(plan.operations))
        return self._text_dialog("完整操作计划 · 核对所有路径与数量", body, confirm)

    def execute_plan(self):
        if not self.plan or self.busy:
            return
        plan, approval = self.plan, token(self.plan)
        if not self._preview_plan(True):
            self.vault.event(plan.id, "用户取消确认", "文件操作未开始")
            return
        if plan.mode == "mirror" and not messagebox.askyesno("镜像清理确认", "已主动选择镜像同步。目标端独有文件将移入隔离区，独有空目录将移除。\n确定执行完整计划？", parent=self, default="no"):
            return
        self.plan = None
        self.execute_button.configure(state="disabled")
        self._run(lambda: self.engine.execute(plan, confirmation=approval, cancel=self.cancel_event, progress=self._progress), self._outcome, "正在复核计划并执行…")

    def _outcome(self, value: Outcome):
        labels = {"completed": "完成", "partial": "部分完成", "failed": "失败", "cancelled": "已取消"}
        description = f"{labels.get(value.status, value.status)}：成功 {value.completed}，跳过 {value.skipped}，失败 {value.failed}\n任务 ID：{value.task_id}"
        self.status.set(description.replace("\n", " · "))
        if self.current_page == "隔离与恢复":
            self._refresh_vault()
        if value.errors:
            self._text_dialog("任务结果", description + "\n\n" + "\n".join(value.errors))
        else:
            messagebox.showinfo("任务结果", description, parent=self)

    def _quarantine_page(self):
        ttk.Label(self.content, text="选择文件后点击“恢复所选”，即可放回原位置；副本会保留，直到你手动删除。", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 12))
        actions = ttk.Frame(self.content)
        actions.grid(row=3, column=0, sticky="ew", pady=10)
        for label, command in (("刷新", self._refresh_vault), ("恢复所选…", lambda: self.maintain_selected("restore")),
                               ("永久删除所选…", lambda: self.maintain_selected("purge")), ("核查中断任务…", self.review_pending)):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 8))
        ttk.Entry(actions, textvariable=self.vault_query, width=20).pack(side="right")
        ttk.Button(actions, text="筛选路径 / 状态", command=self._refresh_vault).pack(side="right", padx=8)
        self.pending_label = ttk.Label(self.content)
        self.pending_label.grid(row=4, column=0, sticky="w", pady=(0, 8))
        self.vault_table = self._table(self.content, 5, ("状态", "时间（UTC）", "类型", "原始路径", "隔离路径", "任务 ID"), (140, 175, 130, 350, 350, 260))
        self._refresh_vault()

    def _refresh_vault(self):
        self.vault_table.delete(*self.vault_table.get_children())
        query = self.vault_query.get().casefold()
        for item in self.vault.items():
            state = STATUS_LABELS.get(item["status"], item["status"])
            if query and query not in (state + item["original"] + item["task_id"]).casefold():
                continue
            self.vault_table.insert("", "end", iid=item["id"], values=(state, item["created"], item["kind"], item["original"], item["stored"], item["task_id"]))
        pending = self.vault.jobs(pending=True)
        self.pending_label.configure(text=f"有 {len(pending)} 个任务意外中断，请先点击“核查中断任务”。" if pending else "", foreground="#ad4824")

    def maintain_selected(self, action):
        if self.busy:
            return
        selected = self.vault_table.selection()
        if not selected:
            messagebox.showinfo("请选择记录", "请先选择一条隔离记录。", parent=self)
            return
        def preview(plan: MaintenancePlan):
            approval = token(plan)
            body = f"操作：{ACTION_LABELS[action]}\n原始路径：{plan.original}\n隔离路径：{plan.stored or '目录结构记录'}\nSHA-256：{plan.expected.digest}\n目标占用：{'是' if plan.current else '否'}\n\n"
            body += "永久删除无法通过此软件撤销。" if action == "purge" else "恢复后保留隔离副本；覆盖前保存当前版本。"
            if not self._text_dialog("隔离操作预览", body, True):
                return
            overwrite, permanent = False, ""
            if action == "restore" and plan.current:
                overwrite = messagebox.askyesno("恢复覆盖确认", f"目标已经存在：\n{plan.original}\n\n明确覆盖并保存当前版本？", parent=self, default="no")
                if not overwrite:
                    return
            if action == "purge":
                permanent = simpledialog.askstring("永久删除 · 二次确认", "此操作不能撤销。请输入：永久删除", parent=self)
                if permanent != "永久删除":
                    return
            self._run(lambda: self.engine.maintain(plan, confirmation=approval, overwrite_confirmation=overwrite,
                                                 permanent_confirmation=permanent, cancel=self.cancel_event), self._outcome, "正在执行隔离操作…")
        self._run(lambda: self.engine.maintenance_plan(selected[0], action), preview, "正在校验隔离副本和目标路径…")

    def review_pending(self):
        pending = self.vault.jobs(pending=True)
        if not pending:
            messagebox.showinfo("中断任务", "无未完成任务。", parent=self)
            return
        if not self._text_dialog("中断任务核查", "\n\n".join(json.dumps(j, ensure_ascii=False, indent=2) for j in pending) +
                                 "\n\n请查看日志、业务目录和隔离副本。未完成步骤不会自动重放。\n确认已完成核查后，可将任务标记为已核查并重新扫描。", True):
            return
        for job in pending:
            self.vault.review_interrupted(job["id"], confirmed=True)
        self._refresh_vault()

    def _tasks_page(self):
        ttk.Label(self.content, text="保存常用文件夹和选项，下次加载后直接扫描。", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 12))
        current = self.config()
        ttk.Label(self.content, text=f"当前源 / 参考：{current.source or '尚未选择'}\n当前目标：{current.target or '尚未选择'}", justify="left").grid(row=2, column=0, sticky="w")
        actions = ttk.Frame(self.content)
        actions.grid(row=3, column=0, sticky="w", pady=15)
        for label, command in (("保存当前配置…", self.save_task), ("加载所选", self.load_selected_task), ("修改所选为当前配置…", self.update_task), ("导入配置…", self.import_task), ("导出当前配置…", self.export_task)):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 7))
        self.tasks_table = self._table(self.content, 4, ("任务名称", "主目录", "目标目录", "配置文件"), (160, 320, 320, 300))
        for path in sorted(self.tasks_dir.glob("*.json")):
            try:
                config = TaskConfig.load(path)
                self.tasks_table.insert("", "end", iid=str(path), values=(config.name, config.source, config.target, str(path)))
            except (OSError, SafetyError) as exc:
                self.vault.event("", "任务配置读取失败", f"{path}: {exc}")

    def save_task(self):
        name = simpledialog.askstring("保存任务", "任务名称：", parent=self)
        if name:
            config = self.config()
            config.name = name
            config.save(self.tasks_dir / (uuid4().hex + ".json"))
            self.show_page("任务管理")

    def update_task(self):
        selected = self.tasks_table.selection()
        if selected and messagebox.askyesno("修改任务配置", "用当前配置更新所选任务？", parent=self, default="no"):
            config = self.config()
            config.name = TaskConfig.load(Path(selected[0])).name
            config.save(Path(selected[0]))
            self.show_page("任务管理")

    def apply_config(self, config: TaskConfig):
        self.source.set(config.source)
        self.target.set(config.target)
        self.rule.set(RULES[config.rule])
        self.case_sensitive.set(config.case_sensitive)
        self.recursive.set(config.recursive)
        self.extensions.set(", ".join(config.extensions))
        self.compare_mode.set("快速比较（大小与时间）" if config.compare_mode == "quick" else "精确比较（SHA-256）")
        self.sync_mode.set("镜像同步" if config.sync_mode == "mirror" else "安全补全")
        self.conflict.set("跳过冲突" if config.conflict == "skip" else "更新并隔离旧版本")
        self.rows = []
        self.show_page("文件夹同步")
        self.status.set(f"已加载任务：{config.name}；请重新扫描。")

    def load_selected_task(self):
        selected = self.tasks_table.selection()
        if selected:
            try:
                self.apply_config(TaskConfig.load(Path(selected[0])))
            except (OSError, SafetyError) as exc:
                messagebox.showerror("配置错误", str(exc), parent=self)

    def import_task(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("任务配置", "*.json")])
        if path:
            try:
                self.apply_config(TaskConfig.load(Path(path)))
            except (OSError, SafetyError) as exc:
                messagebox.showerror("配置错误", str(exc), parent=self)

    def export_task(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("任务配置", "*.json")])
        if path:
            self.config().save(Path(path))

    def _logs_page(self):
        ttk.Label(self.content, text="查看操作记录与失败原因，双击一条记录查看详情。", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 10))
        ttk.Label(self.content, text=f"版本 {__version__}  ·  应用数据：{self.data_root}", justify="left").grid(row=2, column=0, sticky="w")
        actions = ttk.Frame(self.content)
        actions.grid(row=3, column=0, sticky="w", pady=12)
        ttk.Button(actions, text="刷新日志", command=lambda: self.show_page("日志与设置")).pack(side="left")
        ttk.Button(actions, text="导出完整日志…", command=self.export_logs).pack(side="left", padx=8)
        tree = self._table(self.content, 4, ("时间（UTC）", "任务 ID", "类型", "详细信息"), (175, 270, 130, 1000))
        logs = self.vault.logs()
        for i, record in enumerate(logs):
            tree.insert("", "end", iid=str(i), values=(record["created"], record["task_id"], record["kind"], record["detail"]))
        def detail(_):
            selected = tree.selection()
            if selected:
                self._text_dialog("日志详情", json.dumps(logs[int(selected[0])], ensure_ascii=False, indent=2))
        tree.bind("<Double-1>", detail)

    def export_logs(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("日志", "*.json")])
        if path:
            Path(path).write_text(json.dumps(self.vault.logs(1_000_000), ensure_ascii=False, indent=2), encoding="utf-8")

    def export_report(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("差异报告", "*.csv")])
        if path:
            with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("分类", "相对路径", "主目录完整路径", "目标完整路径", "依据/原因"))
                writer.writerows(asdict(row).values() for row in self.rows)

    def _progress(self, path, count, total):
        current = time.monotonic()
        if current - getattr(self, "last_progress", 0) > 0.1 or count == total:
            self.last_progress = current
            self.messages.put(("progress", (path, count, total)))

    def _run(self, work, done, description):
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        self.status.set(description)
        self.cancel_button.configure(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        for button in self.nav_buttons:
            button.configure(state="disabled")
        self.disabled_controls = []
        def disable(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton)):
                    self.disabled_controls.append((widget, widget.cget("state")))
                    widget.configure(state="disabled")
                disable(widget)
        disable(self.content)
        def worker():
            try:
                self.messages.put(("done", (done, work())))
            except Exception as exc:
                if isinstance(exc, Cancelled):
                    self.vault.event("", "用户取消", "预检或后台任务取消，未继续文件操作")
                self.messages.put(("error", exc))
        threading.Thread(target=worker, daemon=False, name="FolderPilot-worker").start()

    def _poll(self):
        for _ in range(100):
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                path, count, total = value
                self.status.set(f"{count}/{total if total else '?'} · {path}")
                if total:
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=total, value=count)
            else:
                self.busy = False
                self.progress.stop()
                self.progress.configure(mode="determinate", value=0)
                self.cancel_button.configure(state="disabled")
                for button in self.nav_buttons:
                    button.configure(state="normal")
                for widget, state in self.disabled_controls:
                    if widget.winfo_exists():
                        widget.configure(state=state)
                self.disabled_controls = []
                self._refresh_actions()
                if self.closing:
                    self.destroy()
                    return
                if kind == "done":
                    callback, result = value
                    callback(result)
                elif isinstance(value, Cancelled):
                    self.status.set("任务已取消，未执行后续步骤。")
                else:
                    self.status.set(f"任务未完成：{value}")
                    self.vault.event("", "界面任务错误", f"{type(value).__name__}: {value}")
                    self._text_dialog("任务错误 · 请核查后重新扫描", f"{type(value).__name__}\n\n{value}")
        self._refresh_display()
        self.after(100, self._poll)

    def _refresh_display(self):
        dpi = window_dpi(self)
        if dpi != self.dpi:
            old_scale = self.scale
            self.dpi, self.scale = dpi, dpi / 96
            self.tk.call("tk", "scaling", dpi / 72)
            self.sidebar.configure(width=self.px(180))
            self._style()
            def resize_tables(parent):
                for widget in parent.winfo_children():
                    if isinstance(widget, ttk.Treeview):
                        for column in widget["columns"]:
                            widget.column(column, width=round(widget.column(column, "width") * self.scale / old_scale))
                    resize_tables(widget)
            resize_tables(self.content)

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.status.set("正在安全停止；当前文件将在安全边界停止。")

    def _close(self):
        if self.busy:
            if messagebox.askyesno("任务尚未结束", "取消后续步骤，等待当前操作安全停止后退出？", parent=self, default="no"):
                self.closing = True
                self.cancel()
        else:
            self.destroy()
