from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class DockerCleanupResult:
    projects: list[str] = field(default_factory=list)
    removed_containers: list[str] = field(default_factory=list)
    removed_networks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def cleanup_harbor_docker(jobs_root: Path, *, job_names: Iterable[str]) -> DockerCleanupResult:
    result = DockerCleanupResult(projects=discover_compose_projects(jobs_root, job_names=job_names))
    container_ids: list[str] = []
    network_ids: list[str] = []
    for project in result.projects:
        container_proc = _run_docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}")
        if container_proc.returncode != 0:
            result.errors.append(_format_error(container_proc))
            continue
        container_ids.extend(_output_lines(container_proc))

        network_proc = _run_docker("network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}")
        if network_proc.returncode != 0:
            result.errors.append(_format_error(network_proc))
            continue
        network_ids.extend(_output_lines(network_proc))

    container_ids = _dedupe(container_ids)
    if container_ids:
        proc = _run_docker("rm", "-f", *container_ids)
        if proc.returncode == 0:
            result.removed_containers.extend(container_ids)
        else:
            result.errors.append(_format_error(proc))

    network_ids = _dedupe(network_ids)
    if network_ids:
        proc = _run_docker("network", "rm", *network_ids)
        if proc.returncode == 0:
            result.removed_networks.extend(network_ids)
        else:
            result.errors.append(_format_error(proc))

    return result


def discover_compose_projects(jobs_root: Path, *, job_names: Iterable[str]) -> list[str]:
    if not jobs_root.exists():
        return []
    projects: set[str] = set()
    for job_name in job_names:
        job_dir = jobs_root / job_name
        if not job_dir.is_dir():
            continue
        for config_path in job_dir.glob("*/config.json"):
            trial_dir = config_path.parent
            if "__" in trial_dir.name and config_path.is_file():
                projects.add(trial_dir.name.lower())
    return sorted(projects)


def format_cleanup_summary(result: DockerCleanupResult) -> str:
    return (
        "docker cleanup: "
        f"{len(result.projects)} project(s), "
        f"{len(result.removed_containers)} container(s), "
        f"{len(result.removed_networks)} network(s)"
    )


def _output_lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _run_docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _format_error(proc: subprocess.CompletedProcess[str]) -> str:
    output = proc.stdout.strip()
    command = " ".join(str(part) for part in proc.args)
    return f"{command} exited {proc.returncode}: {output}"
