import subprocess
from pathlib import Path

from tb2_codex_shim_bench.docker_cleanup import cleanup_harbor_docker, discover_compose_projects, format_cleanup_summary


def test_discover_compose_projects_from_harbor_trial_dirs(tmp_path: Path):
    trial = tmp_path / "jobs" / "run-model-full" / "regex-log__AbC123"
    trial.mkdir(parents=True)
    (trial / "config.json").write_text("{}")
    other_job_trial = tmp_path / "jobs" / "other-run-model-full" / "regex-log__Other"
    other_job_trial.mkdir(parents=True)
    (other_job_trial / "config.json").write_text("{}")
    not_trial = tmp_path / "jobs" / "run-model-full" / "notes"
    not_trial.mkdir()
    (not_trial / "config.json").write_text("{}")

    assert discover_compose_projects(tmp_path / "jobs", job_names=["run-model-full"]) == ["regex-log__abc123"]


def test_cleanup_harbor_docker_removes_only_selected_job_labeled_resources(monkeypatch, tmp_path: Path):
    trial = tmp_path / "jobs" / "run-model-full" / "regex-log__AbC123"
    trial.mkdir(parents=True)
    (trial / "config.json").write_text("{}")
    other_job_trial = tmp_path / "jobs" / "other-run-model-full" / "regex-log__Other"
    other_job_trial.mkdir(parents=True)
    (other_job_trial / "config.json").write_text("{}")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["docker", "ps", "-aq"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="container-1\n")
        if cmd[:4] == ["docker", "network", "ls", "-q"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="network-1\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = cleanup_harbor_docker(tmp_path / "jobs", job_names=["run-model-full"])

    assert result.projects == ["regex-log__abc123"]
    assert result.removed_containers == ["container-1"]
    assert result.removed_networks == ["network-1"]
    assert result.errors == []
    assert calls.count(["docker", "rm", "-f", "container-1"]) == 1
    assert calls.count(["docker", "network", "rm", "network-1"]) == 1
    assert ["docker", "network", "prune", "-f"] not in calls
    assert not any("regex-log__other" in " ".join(call) for call in calls)
    assert format_cleanup_summary(result) == "docker cleanup: 1 project(s), 1 container(s), 1 network(s)"


def test_cleanup_harbor_docker_batches_ids_across_projects(monkeypatch, tmp_path: Path):
    for job_name, trial_name in [("run-a", "regex-log__One"), ("run-b", "fix-git__Two")]:
        trial = tmp_path / "jobs" / job_name / trial_name
        trial.mkdir(parents=True)
        (trial / "config.json").write_text("{}")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        project_arg = next((part for part in cmd if part.startswith("label=com.docker.compose.project=")), "")
        project = project_arg.rsplit("=", 1)[-1]
        if cmd[:3] == ["docker", "ps", "-aq"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{project}-container\n")
        if cmd[:4] == ["docker", "network", "ls", "-q"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{project}-network\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = cleanup_harbor_docker(tmp_path / "jobs", job_names=["run-a", "run-b"])

    assert result.projects == ["fix-git__two", "regex-log__one"]
    assert result.removed_containers == ["fix-git__two-container", "regex-log__one-container"]
    assert result.removed_networks == ["fix-git__two-network", "regex-log__one-network"]
    assert ["docker", "rm", "-f", "fix-git__two-container", "regex-log__one-container"] in calls
    assert ["docker", "network", "rm", "fix-git__two-network", "regex-log__one-network"] in calls
