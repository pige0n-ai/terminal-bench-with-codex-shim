import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tb2_reasonix_bench.agent_setup import config_toml
from tb2_reasonix_bench.config import load_matrix, validate_matrix
from tb2_reasonix_bench.harbor import run_harbor
from tb2_reasonix_bench.summary import summarize_run


def write_matrix(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "matrix.reasonix.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def base_matrix() -> dict:
    return {
        "defaults": {
            "harbor_dataset": "terminal-bench/terminal-bench-2-1",
            "harbor_jobs_dir": "runs",
            "harbor_n_attempts": 2,
            "harbor_n_concurrent": 3,
            "reasonix_version": "1.0.0",
            "auto_plan": "off",
            "permissions_mode": "allow",
            "tasks": ["terminal-bench/regex-log"],
        },
        "models": [
            {
                "id": "deepseek_v4_flash",
                "model_slug": "deepseek-v4-flash",
                "provider_name": "deepseek-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com",
            }
        ],
    }


def test_load_matrix_and_metadata(tmp_path: Path):
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    model = matrix.models[0]

    assert model.reasonix_model() == "deepseek-v4-flash"
    metadata = model.resolved_metadata(matrix.defaults)
    assert metadata["permissions_mode"] == "allow"
    assert "secret-key" not in json.dumps(metadata)


def test_rejects_unknown_auto_plan(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["auto_plan"] = "sometimes"

    with pytest.raises(ValueError, match="defaults.auto_plan must be one of"):
        load_matrix(write_matrix(tmp_path, data))


def test_check_env_rejects_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        validate_matrix(matrix, check_env=True)


def test_run_harbor_uses_reasonix_agent_and_hides_secret(monkeypatch, tmp_path: Path):
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
    assert cmd[cmd.index("--agent-import-path") + 1] == "tb2_reasonix_bench.harbor_agent:PinnedReasonix"
    assert cmd[cmd.index("--model") + 1] == "deepseek-v4-flash"
    assert "reasonix_version=1.0.0" in cmd
    assert "permissions_mode=allow" in cmd
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


def test_reasonix_config_toml_content():
    text = config_toml(
        provider_name="deepseek-flash",
        model_slug="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        auto_plan="off",
        planner_model="deepseek-pro",
        subagent_model=None,
        permissions_mode="allow",
    )

    assert 'default_model = "deepseek-flash"' in text
    assert 'planner_model = "deepseek-pro"' in text
    assert 'model = "deepseek-v4-flash"' in text
    assert 'api_key_env = "DEEPSEEK_API_KEY"' in text
    assert 'mode = "allow"' in text


def test_summary_reads_reasonix_usage_lines(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    agent_dir = result_dir / "agent"
    agent_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "build-cython-ext",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-flash"}},
                "agent_result": {},
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        )
    )
    (agent_dir / "reasonix.txt").write_text(
        "\n".join(
            [
                "\x1b[2m  ▎ thinking\x1b[0m",
                "  · 8434 tok · in 7985 (0 cached / 7985 new) · out 449 (106 reasoning) · ¥0.0089",
                '  -> bash {"command": "git clone"}',
                "  · 8514 tok · in 8426 (7936 cached / 490 new) · out 88 (8 reasoning) · ¥0.0008",
                '  -> read_file {"path": "/app/setup.py"}',
            ]
        )
    )

    trial = summarize_run(tmp_path)["trials"][0]

    assert trial["n_requests"] == 2
    assert trial["n_turns"] == 2
    assert trial["n_tool_calls"] == 2
    assert trial["n_input_tokens"] == 16411
    assert trial["n_cache_read_tokens"] == 7936
    assert trial["n_cache_creation_tokens"] == 8475
    assert trial["n_cache_tokens"] == 7936
    assert trial["n_output_tokens"] == 537
    assert trial["n_reasoning_tokens"] == 114
    assert trial["n_total_tokens"] == 16948
    assert trial["cost_usd"] == pytest.approx(0.0097)


def test_cli_smoke_records_prefixed_job(monkeypatch, tmp_path: Path):
    from tb2_reasonix_bench import cli

    calls = []

    def fake_run_harbor(**kwargs):
        calls.append(kwargs)
        return type("Result", (), {"return_code": 0, "stdout": "ok", "command": ["harbor"]})()

    monkeypatch.setattr(cli, "run_harbor", fake_run_harbor)
    monkeypatch.setattr(cli, "cleanup_harbor_docker", lambda *args, **kwargs: type("Cleanup", (), {"projects": [], "removed_containers": [], "removed_networks": [], "errors": []})())
    matrix_path = write_matrix(tmp_path, base_matrix())

    assert cli.main(["smoke", "--matrix", str(matrix_path), "--model", "deepseek_v4_flash", "--task", "regex-log", "--run-name", "probe"]) == 0

    assert calls
    assert calls[0]["job_name"].startswith("reasonix-probe-deepseek_v4_flash-regex-log-")
