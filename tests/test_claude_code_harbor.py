import subprocess
from pathlib import Path

from tb2_claude_code_bench.config import Defaults, ModelEntry
from tb2_claude_code_bench.harbor import run_harbor


def test_run_harbor_uses_claude_code_agent_and_deepseek_env(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setattr(subprocess, "run", fake_run)

    defaults = Defaults(
        harbor_bin="harbor",
        harbor_dataset="terminal-bench/terminal-bench-2-1",
        harbor_n_attempts=5,
        harbor_n_concurrent=6,
        claude_code_version="2.1.144",
        temperature=0.0,
        thinking_display="omitted",
        disallowed_tools="WebSearch,WebFetch",
    )
    model = ModelEntry(
        id="deepseek_v4_flash_nonthinking",
        model_slug="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        anthropic_base_url="https://api.deepseek.com/anthropic",
        thinking="disabled",
        reasoning_effort="high",
    )

    result = run_harbor(
        defaults=defaults,
        model=model,
        jobs_dir=tmp_path / "jobs",
        job_name="probe",
        tasks=["regex-log"],
        repo_root=tmp_path,
    )

    assert result.return_code == 0
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-import-path") + 1] == "tb2_claude_code_bench.harbor_agent:PinnedClaudeCode"
    assert cmd[cmd.index("--model") + 1] == "deepseek-v4-flash"
    assert cmd[cmd.index("-d") + 1] == "terminal-bench/terminal-bench-2-1"
    assert cmd[cmd.index("--n-attempts") + 1] == "5"
    assert cmd[cmd.index("--n-concurrent") + 1] == "6"
    assert "version=2.1.144" in cmd
    assert "thinking=disabled" in cmd
    assert "reasoning_effort=high" in cmd
    assert "thinking_display=omitted" in cmd
    assert "disallowed_tools=WebSearch,WebFetch" in cmd
    assert cmd[cmd.index("--include-task-name") + 1] == "regex-log"
    assert "secret-key" not in " ".join(cmd)
    assert "--ae" in cmd
    assert "CLAUDE_CODE_EXTRA_BODY={\"temperature\":0.0}" in cmd

    env = captured["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "secret-key"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret-key"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "deepseek-v4-flash"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deepseek-v4-flash"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "deepseek-v4-flash"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "deepseek-v4-flash"


def test_run_harbor_full_dataset_has_no_task_filter(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setattr(subprocess, "run", fake_run)

    defaults = Defaults()
    model = ModelEntry("deepseek", "deepseek-v4-flash", "DEEPSEEK_API_KEY", "https://api.deepseek.com/anthropic")
    run_harbor(defaults=defaults, model=model, jobs_dir=tmp_path / "jobs", job_name="probe", tasks=[], repo_root=tmp_path)

    assert "--include-task-name" not in captured["cmd"]
    assert "--task" not in captured["cmd"]
