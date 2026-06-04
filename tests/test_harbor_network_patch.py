import json
import subprocess
from pathlib import Path

from tb2_harbor_network_patch import _allocate_subnet


def test_allocate_subnet_skips_existing_and_records_registry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TB2_HARBOR_NETWORK_POOL_CIDR", "10.240.0.0/29")
    monkeypatch.setenv("TB2_HARBOR_NETWORK_SUBNET_PREFIX", "30")
    monkeypatch.setenv("TB2_HARBOR_NETWORK_REGISTRY", str(tmp_path / "registry.json"))

    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "network-a\n")

    def fake_run(cmd, **kwargs):
        assert cmd == ["docker", "network", "inspect", "network-a"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps([{"IPAM": {"Config": [{"Subnet": "10.240.0.0/30"}]}}]),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _allocate_subnet("session-a") == "10.240.0.4/30"
    assert json.loads((tmp_path / "registry.json").read_text()) == {"session-a": {"subnet": "10.240.0.4/30"}}


def test_allocate_subnet_rejects_exhausted_pool(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TB2_HARBOR_NETWORK_POOL_CIDR", "10.240.0.0/30")
    monkeypatch.setenv("TB2_HARBOR_NETWORK_SUBNET_PREFIX", "30")
    monkeypatch.setenv("TB2_HARBOR_NETWORK_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "network-a\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps([{"IPAM": {"Config": [{"Subnet": "10.240.0.0/30"}]}}]),
            stderr="",
        ),
    )

    try:
        _allocate_subnet("session-a")
    except RuntimeError as exc:
        assert "no free Docker subnet" in str(exc)
    else:
        raise AssertionError("expected exhausted pool to raise")
