import subprocess
from pathlib import Path

from tb2_codex_shim_bench.config import Defaults, ModelEntry
from tb2_codex_shim_bench.harbor import run_harbor


def test_run_harbor_filters_terminal_bench_dataset_task(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake_run)

    defaults = Defaults(codex_shim_bin=Path("/bin/echo"), harbor_dataset="terminal-bench@2.0", harbor_n_attempts=5)
    model = ModelEntry(
        id="deepseek_v4_flash",
        provider_profile="deepseek-chat",
        model_slug="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        port=8877,
    )

    result = run_harbor(
        defaults=defaults,
        model=model,
        codex_shim_base_url="http://host.docker.internal:8877/v1",
        model_catalog_json='{"models":[{"slug":"deepseek-v4-flash"}]}',
        jobs_dir=tmp_path / "jobs",
        job_name="probe",
        tasks=["regex-log"],
        repo_root=tmp_path,
    )

    assert result.return_code == 0
    assert captured["cmd"][captured["cmd"].index("-d") + 1] == "terminal-bench@2.0"
    assert "--task" not in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--include-task-name") + 1] == "regex-log"
    assert captured["cmd"][captured["cmd"].index("--n-attempts") + 1] == "5"
    assert "codex_cli_version=0.131.0" in captured["cmd"]
    assert "node_version=22" in captured["cmd"]
    assert "nvm_version=0.40.2" in captured["cmd"]
    assert "root_packages=curl,ripgrep" in captured["cmd"]
    assert "alpine_packages=curl,bash,nodejs,npm,ripgrep" in captured["cmd"]


def test_run_harbor_full_dataset_has_no_task_filter(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake_run)

    defaults = Defaults(codex_shim_bin=Path("/bin/echo"))
    model = ModelEntry(
        id="deepseek_v4_flash",
        provider_profile="deepseek-chat",
        model_slug="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        port=8877,
    )

    run_harbor(
        defaults=defaults,
        model=model,
        codex_shim_base_url="http://host.docker.internal:8877/v1",
        model_catalog_json='{"models":[{"slug":"deepseek-v4-flash"}]}',
        jobs_dir=tmp_path / "jobs",
        job_name="probe",
        tasks=[],
        repo_root=tmp_path,
    )

    assert "--include-task-name" not in captured["cmd"]
    assert "--task" not in captured["cmd"]
