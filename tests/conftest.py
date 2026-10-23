from pathlib import Path
import pytest
from folderpilot.storage import Vault
from folderpilot.engine import Engine
from folderpilot.scan import scan
from uuid import uuid4


def pytest_configure(config):
    # Keep every generated file inside this project; do not depend on global TEMP ACLs.
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        config.option.basetemp = str(root / ("run-" + uuid4().hex))


@pytest.fixture
def folders(tmp_path):
    source, target = tmp_path / "主目录", tmp_path / "副目录"
    source.mkdir()
    target.mkdir()
    return source, target


@pytest.fixture
def engine(tmp_path):
    return Engine(Vault(tmp_path / "隔离存储"))


def write(root: Path, relative: str, content: str = "hello") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def snapshots(folders, **kwargs):
    return tuple(scan(p, **kwargs) for p in folders)
