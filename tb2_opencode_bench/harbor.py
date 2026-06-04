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
        "tb2_opencode_bench.harbor_agent:PinnedOpenCode",
        "--model",
        model.opencode_model(),
        "--ak",
        f"opencode_version={defaults.opencode_version}",
        "--ak",
        f"node_version={defaults.node_version}",
        "--ak",
        f"nvm_version={defaults.nvm_version}",
        "--ak",
        f"root_packages={','.join(defaults.root_packages)}",
        "--ak",
        f"alpine_packages={','.join(defaults.alpine_packages)}",
        "--ak",
        f"provider_id={model.provider_id}",
        "--ak",
        f"provider_name={model.provider_name}",
        "--ak",
        f"api_key_env={model.api_key_env}",
        "--ak",
        f"base_url={model.base_url}",
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        job_name,
        "--yes",
    ]
    _append_agent_kwarg(cmd, "context_window", model.context_window)
    _append_agent_kwarg(cmd, "max_output_tokens", model.max_output_tokens)
    for key, value in sorted(model.extra_env.items()):
        cmd.extend(["--ae", f"{key}={value}"])
    if tasks:
        cmd.extend(["--include-task-name", tasks[0]])

    env = os.environ.copy()
    env[model.api_key_env] = api_key
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
