import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tb2_codewhale_bench.agent_setup import runtime_env
from tb2_codewhale_bench.config import load_matrix, validate_matrix
from tb2_codewhale_bench.harbor import run_harbor


def write_matrix(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "matrix.codewhale.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def base_matrix() -> dict:
    return {
        "defaults": {
            "harbor_dataset": "terminal-bench/terminal-bench-2-1",
            "harbor_jobs_dir": "runs",
            "harbor_n_attempts": 2,
            "harbor_n_concurrent": 3,
            "codewhale_version": "0.8.50",
            "yolo": True,
            "stream_idle_timeout_secs": 300,
            "tasks": ["terminal-bench/regex-log"],
        },
        "models": [
            {
                "id": "deepseek_v4_flash",
                "model_slug": "deepseek-v4-flash",
                "provider": "deepseek",
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com/beta",
                "thinking": "high",
            }
        ],
    }


def test_load_matrix_and_metadata(tmp_path: Path):
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    model = matrix.models[0]

    assert model.resolved_yolo(matrix.defaults) is True
    assert model.resolved_stream_idle_timeout_secs(matrix.defaults) == 300
    metadata = model.resolved_metadata(matrix.defaults)
    assert metadata["codewhale_version"] == "0.8.50"
    assert "secret-key" not in json.dumps(metadata)


def test_rejects_unknown_provider(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["provider"] = "mystery"

    with pytest.raises(ValueError, match="unsupported codewhale provider"):
        load_matrix(write_matrix(tmp_path, data))


def test_check_env_rejects_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        validate_matrix(matrix, check_env=True)


def test_run_harbor_uses_codewhale_agent_and_hides_secret(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setattr(subprocess, "run", fake_run)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    result = run_harbor(defaults=matrix.defaults, model=matrix.models[0], jobs_dir=tmp_path / "jobs", job_name="probe", tasks=["regex-log"], repo_root=tmp_path)

    assert result.return_code == 0
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-import-path") + 1] == "tb2_codewhale_bench.harbor_agent:PinnedCodeWhale"
    assert cmd[cmd.index("--model") + 1] == "deepseek-v4-flash"
    assert "codewhale_version=0.8.50" in cmd
    assert "provider=deepseek" in cmd
    assert "yolo=true" in cmd
    assert "thinking=high" in cmd
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


def test_codewhale_runtime_env_content():
    env = runtime_env(
        provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        api_key="secret-key",
        base_url="https://api.deepseek.com/beta",
        model_slug="deepseek-v4-flash",
        codewhale_home="/tmp/agent/codewhale-home",
        stream_idle_timeout_secs=300,
    )

    assert env["CODEWHALE_PROVIDER"] == "deepseek"
    assert env["DEEPSEEK_API_KEY"] == "secret-key"
    assert env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com/beta"
    assert env["DEEPSEEK_MODEL"] == "deepseek-v4-flash"
    assert env["CODEWHALE_HOME"] == "/tmp/agent/codewhale-home"
    assert env["DEEPSEEK_STREAM_IDLE_TIMEOUT_SECS"] == "300"


def test_codewhale_runtime_env_maps_custom_key_to_native_provider_env():
    env = runtime_env(
        provider="deepseek",
        api_key_env="CODEWHALE_DEEPSEEK_API_KEY",
        api_key="agent-specific-key",
        base_url="https://api.deepseek.com/beta",
        model_slug="deepseek-v4-flash",
        codewhale_home="/tmp/agent/codewhale-home",
        stream_idle_timeout_secs=None,
    )

    assert env["CODEWHALE_DEEPSEEK_API_KEY"] == "agent-specific-key"
    assert env["DEEPSEEK_API_KEY"] == "agent-specific-key"


def test_cli_smoke_records_prefixed_job(monkeypatch, tmp_path: Path):
    from tb2_codewhale_bench import cli

    calls = []

    def fake_run_harbor(**kwargs):
        calls.append(kwargs)
        return type("Result", (), {"return_code": 0, "stdout": "ok", "command": ["harbor"]})()

    monkeypatch.setattr(cli, "run_harbor", fake_run_harbor)
    monkeypatch.setattr(cli, "cleanup_harbor_docker", lambda *args, **kwargs: type("Cleanup", (), {"projects": [], "removed_containers": [], "removed_networks": [], "errors": []})())
    matrix_path = write_matrix(tmp_path, base_matrix())

    assert cli.main(["smoke", "--matrix", str(matrix_path), "--model", "deepseek_v4_flash", "--task", "regex-log", "--run-name", "probe"]) == 0

    assert calls
    assert calls[0]["job_name"].startswith("codewhale-probe-deepseek_v4_flash-regex-log-")
