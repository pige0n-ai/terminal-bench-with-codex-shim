from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Defaults, ModelEntry


@dataclass(frozen=True)
class HarborRunResult:
    command: list[str]
    return_code: int
    stdout: str


def run_harbor(
    *,
    defaults: Defaults,
    model: ModelEntry,
    jobs_dir: Path,
    job_name: str,
    tasks: list[str],
    repo_root: Path,
) -> HarborRunResult:
    if len(tasks) > 1:
        raise ValueError("run_harbor accepts at most one --include-task-name value per Harbor invocation")

    api_key = os.environ.get(model.api_key_env)
    if not api_key:
        raise ValueError(f"required env var is not set: {model.api_key_env}")

    jobs_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        defaults.harbor_bin,
        "run",
        "-d",
        defaults.harbor_dataset,
        "--n-attempts",
        str(defaults.harbor_n_attempts),
        "--n-concurrent",
        str(defaults.harbor_n_concurrent),
        "--agent-import-path",
        "tb2_claude_code_bench.harbor_agent:PinnedClaudeCode",
        "--model",
        model.model_slug,
        "--ak",
        f"version={defaults.claude_code_version}",
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        job_name,
        "--yes",
    ]

    _append_agent_kwarg(cmd, "thinking", model.thinking or defaults.thinking)
    _append_agent_kwarg(cmd, "reasoning_effort", model.reasoning_effort or defaults.reasoning_effort)
    _append_agent_kwarg(cmd, "thinking_display", model.thinking_display or defaults.thinking_display)
    _append_agent_kwarg(cmd, "max_thinking_tokens", model.max_thinking_tokens or defaults.max_thinking_tokens)
    _append_agent_kwarg(cmd, "max_turns", model.max_turns or defaults.max_turns)
    _append_agent_kwarg(cmd, "max_budget_usd", model.max_budget_usd or defaults.max_budget_usd)
    _append_agent_kwarg(cmd, "fallback_model", model.fallback_model or defaults.fallback_model)
    _append_agent_kwarg(cmd, "allowed_tools", model.allowed_tools or defaults.allowed_tools)
    _append_agent_kwarg(cmd, "disallowed_tools", model.disallowed_tools or defaults.disallowed_tools)

    for key, value in sorted(model.resolved_extra_env(defaults).items()):
        cmd.extend(["--ae", f"{key}={value}"])

    if tasks:
        cmd.extend(["--include-task-name", tasks[0]])

    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = model.anthropic_base_url
    # Harbor's ClaudeCode agent reads ANTHROPIC_API_KEY and sends it into the
    # trial container. DeepSeek's Anthropic-compatible endpoint supports x-api-key.
    env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_AUTH_TOKEN"] = api_key
    env["ANTHROPIC_MODEL"] = model.model_slug
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model.model_slug
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model.model_slug
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = model.model_slug
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = model.model_slug
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo_root) if not pythonpath else f"{repo_root}:{pythonpath}"

    result = subprocess.run(
        cmd,
        cwd=repo_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return HarborRunResult(command=cmd, return_code=result.returncode, stdout=result.stdout)


def _append_agent_kwarg(cmd: list[str], key: str, value: object | None) -> None:
    if value is None:
        return
    cmd.extend(["--ak", f"{key}={value}"])
