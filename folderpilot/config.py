"""Versioned task documents; no machine-specific defaults."""
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from uuid import uuid4
from .models import SafetyError


@dataclass
class TaskConfig:
    version: int = 1
    name: str = "常用任务"
    source: str = ""
    target: str = ""
    recursive: bool = True
    rule: str = "stem"
    case_sensitive: bool = False
    extensions: tuple[str, ...] = ()
    compare_mode: str = "exact"
    sync_mode: str = "complete"
    conflict: str = "update"
    cleanup_policy: str = "quarantine"

    def validate(self) -> None:
        if self.version != 1 or isinstance(self.version, bool):
            raise SafetyError("不支持的任务格式版本")
        if self.rule not in {"name", "stem", "path", "path_stem"}:
            raise SafetyError("未知匹配规则")
        if self.compare_mode not in {"exact", "quick"} or self.sync_mode not in {"complete", "mirror"}:
            raise SafetyError("未知比较或同步模式")
        if self.conflict not in {"update", "skip"} or self.cleanup_policy != "quarantine":
            raise SafetyError("不支持的冲突/清理策略")
        if not all(isinstance(v, str) for v in (self.name, self.source, self.target)):
            raise SafetyError("任务名称与路径必须为字符串")
        if not isinstance(self.recursive, bool) or not isinstance(self.case_sensitive, bool):
            raise SafetyError("递归和大小写选项必须为布尔值")
        if not isinstance(self.extensions, (tuple, list)) or not all(isinstance(v, str) for v in self.extensions):
            raise SafetyError("扩展名必须为字符串数组")

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(asdict(self), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path: Path) -> "TaskConfig":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)} or "version" not in data:
                raise SafetyError("任务文档格式错误或包含未知字段")
            config = cls(**data)
            config.validate()
            config.extensions = tuple(config.extensions)
            return config
        except (ValueError, TypeError) as exc:
            raise SafetyError(f"任务配置无效：{exc}") from exc
