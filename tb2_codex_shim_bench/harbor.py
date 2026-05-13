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
    codex_shim_base_url: str,
    jobs_dir: Path,
    job_name: str,
    tasks: list[str],
    repo_root: Path,
) -> HarborRunResult:
    if len(tasks) > 1:
        raise ValueError("run_harbor accepts at most one --include-task-name value per Harbor invocation")

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
        "tb2_codex_shim_bench.harbor_agent:ShimmedCodex",
        "--model",
        model.codex_model(),
        "--ak",
        f"codex_shim_base_url={codex_shim_base_url}",
        "--ak",
        f"reasoning_effort={model.reasoning_effort or defaults.reasoning_effort}",
        "--ak",
        f"context_window={model.context_window or defaults.context_window}",
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        job_name,
        "--yes",
    ]
    if tasks:
        cmd.extend(["--include-task-name", tasks[0]])

    env = os.environ.copy()
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
