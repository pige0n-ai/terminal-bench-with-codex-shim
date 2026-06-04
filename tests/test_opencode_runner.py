import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tb2_opencode_bench.agent_setup import config_json
from tb2_opencode_bench.config import load_matrix, validate_matrix
from tb2_opencode_bench.harbor import run_harbor


def write_matrix(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "matrix.opencode.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def base_matrix() -> dict:
    return {
        "defaults": {
            "harbor_dataset": "terminal-bench/terminal-bench-2-1",
            "harbor_jobs_dir": "runs",
            "harbor_n_attempts": 2,
            "harbor_n_concurrent": 3,
            "opencode_version": "1.15.13",
            "tasks": ["terminal-bench/regex-log"],
        },
        "models": [
            {
                "id": "deepseek_v4_flash",
                "model_slug": "deepseek-v4-flash",
                "provider_id": "deepseek",
                "provider_name": "DeepSeek",
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com/v1",
                "context_window": 1000000,
                "max_output_tokens": 65536,
            }
        ],
    }


def test_load_matrix_and_metadata(tmp_path: Path):
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    model = matrix.models[0]

    assert matrix.defaults.harbor_jobs_dir == tmp_path / "runs"
    assert model.opencode_model() == "deepseek/deepseek-v4-flash"
    metadata = model.resolved_metadata(matrix.defaults)
    assert metadata["opencode_version"] == "1.15.13"
    assert "secret-key" not in json.dumps(metadata)


def test_check_env_rejects_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        validate_matrix(matrix, check_env=True)


def test_run_harbor_uses_opencode_agent_and_hides_secret(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setattr(subprocess, "run", fake_run)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    model = matrix.models[0]

    result = run_harbor(defaults=matrix.defaults, model=model, jobs_dir=tmp_path / "jobs", job_name="probe", tasks=["regex-log"], repo_root=tmp_path)

    assert result.return_code == 0
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-import-path") + 1] == "tb2_opencode_bench.harbor_agent:PinnedOpenCode"
    assert cmd[cmd.index("--model") + 1] == "deepseek/deepseek-v4-flash"
    assert "opencode_version=1.15.13" in cmd
    assert "provider_id=deepseek" in cmd
    assert "context_window=1000000" in cmd
    assert cmd[cmd.index("--include-task-name") + 1] == "regex-log"
    assert "secret-key" not in " ".join(cmd)
    assert captured["env"]["DEEPSEEK_API_KEY"] == "secret-key"


def test_run_harbor_full_dataset_has_no_task_filter(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setattr(subprocess, "run", fake_run)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    run_harbor(defaults=matrix.defaults, model=matrix.models[0], jobs_dir=tmp_path / "jobs", job_name="probe", tasks=[], repo_root=tmp_path)

    assert "--include-task-name" not in captured["cmd"]


def test_opencode_config_json_content():
    parsed = json.loads(
        config_json(
            provider_id="deepseek",
            provider_name="DeepSeek",
            model_slug="deepseek-v4-flash",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com/v1",
            context_window=1000000,
            max_output_tokens=65536,
        )
    )

    assert parsed["model"] == "deepseek/deepseek-v4-flash"
    provider = parsed["provider"]["deepseek"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["apiKey"] == "{env:DEEPSEEK_API_KEY}"
    assert provider["models"]["deepseek-v4-flash"]["limit"] == {"context": 1000000, "output": 65536}


def test_cli_smoke_records_prefixed_job(monkeypatch, tmp_path: Path):
    from tb2_opencode_bench import cli

    calls = []

    def fake_run_harbor(**kwargs):
        calls.append(kwargs)
        return type("Result", (), {"return_code": 0, "stdout": "ok", "command": ["harbor"]})()

    monkeypatch.setattr(cli, "run_harbor", fake_run_harbor)
    monkeypatch.setattr(cli, "cleanup_harbor_docker", lambda *args, **kwargs: type("Cleanup", (), {"projects": [], "removed_containers": [], "removed_networks": [], "errors": []})())
    matrix_path = write_matrix(tmp_path, base_matrix())

    assert cli.main(["smoke", "--matrix", str(matrix_path), "--model", "deepseek_v4_flash", "--task", "regex-log", "--run-name", "probe"]) == 0

    assert calls
    assert calls[0]["job_name"].startswith("opencode-probe-deepseek_v4_flash-regex-log-")
