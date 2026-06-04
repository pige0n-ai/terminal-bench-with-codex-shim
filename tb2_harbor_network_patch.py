from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import subprocess
from pathlib import Path
from typing import Any


_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from harbor.environments.docker.docker import DockerEnvironment

    original_getter = DockerEnvironment._docker_compose_paths.fget
    if original_getter is None:
        raise RuntimeError("Harbor DockerEnvironment._docker_compose_paths has no getter")

    def patched_compose_paths(self: Any) -> list[Path]:
        paths = list(original_getter(self))
        paths.append(_network_override_path(self))
        return paths

    DockerEnvironment._docker_compose_paths = property(patched_compose_paths)
    _INSTALLED = True


def _network_override_path(environment: Any) -> Path:
    cached = getattr(environment, "_tb2_network_override_path", None)
    if cached:
        return cached

    subnet = _allocate_subnet(str(environment.session_id))
    path = Path(environment.trial_paths.trial_dir) / "docker-compose-tb2-network.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "networks": {
                    "default": {
                        "ipam": {
                            "config": [
                                {
                                    "subnet": subnet,
                                }
                            ]
                        }
                    }
                }
            },
            indent=2,
        )
    )
    setattr(environment, "_tb2_network_override_path", path)
    return path


def _allocate_subnet(session_id: str) -> str:
    pool = ipaddress.ip_network(_required_env("TB2_HARBOR_NETWORK_POOL_CIDR"))
    prefix = int(_required_env("TB2_HARBOR_NETWORK_SUBNET_PREFIX"))
    if prefix < pool.prefixlen:
        raise RuntimeError(f"network subnet prefix {prefix} is smaller than pool prefix {pool.prefixlen}")
    if prefix > 30:
        raise RuntimeError("network subnet prefix must be <= 30 so Docker has usable addresses")

    registry_path = Path(_required_env("TB2_HARBOR_NETWORK_REGISTRY"))
    lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        registry = _read_registry(registry_path)
        existing = _docker_network_subnets()
        reserved = {
            ipaddress.ip_network(item["subnet"])
            for item in registry.values()
            if isinstance(item, dict) and item.get("subnet")
        }
        if session_id in registry:
            subnet = ipaddress.ip_network(registry[session_id]["subnet"])
            if not any(subnet.overlaps(item) for item in existing):
                return str(subnet)

        blocked = existing | reserved
        for subnet in pool.subnets(new_prefix=prefix):
            if any(subnet.overlaps(item) for item in blocked):
                continue
            registry[session_id] = {"subnet": str(subnet)}
            registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True))
            return str(subnet)

    raise RuntimeError(f"no free Docker subnet in {pool} with prefix /{prefix}")


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid Docker subnet registry JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Docker subnet registry must be a JSON object: {path}")
    return value


def _docker_network_subnets() -> set[ipaddress._BaseNetwork]:
    result = subprocess.run(
        ["docker", "network", "inspect", *subprocess.check_output(["docker", "network", "ls", "-q"], text=True).split()],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker network inspect failed: {result.stderr or result.stdout}")
    subnets: set[ipaddress._BaseNetwork] = set()
    data = json.loads(result.stdout)
    for network in data:
        for item in (network.get("IPAM") or {}).get("Config") or []:
            subnet = item.get("Subnet")
            if subnet:
                subnets.add(ipaddress.ip_network(subnet))
    return subnets


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required env var is not set: {name}")
    return value
