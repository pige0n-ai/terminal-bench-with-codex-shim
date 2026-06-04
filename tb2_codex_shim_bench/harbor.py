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
    model_catalog_json: str,
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
        "--ak",
        f"model_catalog_json={model_catalog_json}",
        "--ak",
        f"codex_cli_version={defaults.codex_cli_version}",
        "--ak",
        f"node_version={defaults.node_version}",
        "--ak",
        f"nvm_version={defaults.nvm_version}",
        "--ak",
        f"root_packages={','.join(defaults.root_packages)}",
        "--ak",
        f"alpine_packages={','.join(defaults.alpine_packages)}",
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
    _apply_docker_network_env(env, defaults, jobs_dir)

    result = subprocess.run(
        cmd,
        cwd=repo_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return HarborRunResult(command=cmd, return_code=result.returncode, stdout=result.stdout)


def _apply_docker_network_env(env: dict[str, str], defaults: Defaults, jobs_dir: Path) -> None:
    if defaults.docker_network_pool_cidr is None:
        return
    env["TB2_HARBOR_NETWORK_POOL_CIDR"] = defaults.docker_network_pool_cidr
    env["TB2_HARBOR_NETWORK_SUBNET_PREFIX"] = str(defaults.docker_network_subnet_prefix or 24)
    env["TB2_HARBOR_NETWORK_REGISTRY"] = str(jobs_dir.parent / "docker-network-subnets.json")
