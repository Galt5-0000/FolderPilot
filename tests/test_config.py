import json
import pytest
from folderpilot.config import TaskConfig
from folderpilot.models import SafetyError


def test_config_round_trip(tmp_path):
    config = TaskConfig(name="中文任务", extensions=(".txt", ".csv"), sync_mode="mirror", recursive=False)
    path = tmp_path / "task.json"
    config.save(path)
    assert TaskConfig.load(path) == config


@pytest.mark.parametrize("value", [{"version": 99}, {"version": 1, "unknown": 1},
                                  {"version": 1, "recursive": "false"},
                                  {"version": 1, "cleanup_policy": "delete"},
                                  {"version": 1, "extensions": "*.txt"}, {}])
def test_invalid_config(tmp_path, value):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value))
    with pytest.raises(SafetyError):
        TaskConfig.load(path)
