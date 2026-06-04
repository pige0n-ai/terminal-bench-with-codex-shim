from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Defaults:
    harbor_bin: str = "harbor"
    harbor_dataset: str = "terminal-bench/terminal-bench-2-1"
    harbor_jobs_dir: Path = Path("runs")
    harbor_n_attempts: int = 1
    harbor_n_concurrent: int = 1
    opencode_version: str = "1.15.13"
    node_version: str = "22"
    nvm_version: str = "0.40.2"
    root_packages: list[str] = field(default_factory=lambda: ["curl", "ripgrep"])
    alpine_packages: list[str] = field(default_factory=lambda: ["curl", "bash", "nodejs", "npm", "ripgrep"])
    docker_network_pool_cidr: str | None = None
    docker_network_subnet_prefix: int | None = None
    tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelEntry:
    id: str
    model_slug: str
    provider_id: str
    provider_name: str
    api_key_env: str
    base_url: str
    context_window: int | None = None
    max_output_tokens: int | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    def opencode_model(self) -> str:
        return f"{self.provider_id}/{self.model_slug}"

    def resolved_metadata(self, defaults: Defaults) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "id": self.id,
            "model_slug": self.model_slug,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "opencode_version": defaults.opencode_version,
            "extra_env": dict(self.extra_env),
        }
        if self.context_window is not None:
            metadata["context_window"] = self.context_window
        if self.max_output_tokens is not None:
            metadata["max_output_tokens"] = self.max_output_tokens
        return metadata


@dataclass(frozen=True)
class MatrixConfig:
    path: Path
    defaults: Defaults
    models: list[ModelEntry]

    def model_by_id(self, model_id: str) -> ModelEntry:
        for model in self.models:
            if model.id == model_id:
                return model
        known = ", ".join(model.id for model in self.models)
        raise ValueError(f"unknown model id '{model_id}'. Known models: {known}")


def load_matrix(path: Path) -> MatrixConfig:
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("matrix root must be a mapping")

    defaults_raw = _mapping(raw.get("defaults", {}), "defaults")
    models_raw = raw.get("models")
    if not isinstance(models_raw, list) or not models_raw:
        raise ValueError("matrix must contain a non-empty 'models' list")

    base = path.parent
    defaults = Defaults(
        harbor_bin=str(defaults_raw.get("harbor_bin", "harbor")),
        harbor_dataset=str(defaults_raw.get("harbor_dataset", "terminal-bench/terminal-bench-2-1")),
        harbor_jobs_dir=_resolve_path(base, str(defaults_raw.get("harbor_jobs_dir", "runs"))),
        harbor_n_attempts=_positive_int(defaults_raw.get("harbor_n_attempts", 1), "defaults.harbor_n_attempts"),
        harbor_n_concurrent=_positive_int(defaults_raw.get("harbor_n_concurrent", 1), "defaults.harbor_n_concurrent"),
        opencode_version=_required_str(defaults_raw.get("opencode_version", "1.15.13"), "defaults.opencode_version"),
        node_version=_required_str(defaults_raw.get("node_version", "22"), "defaults.node_version"),
        nvm_version=_required_str(defaults_raw.get("nvm_version", "0.40.2"), "defaults.nvm_version"),
        root_packages=_string_list(defaults_raw.get("root_packages", ["curl", "ripgrep"]), "defaults.root_packages"),
        alpine_packages=_string_list(defaults_raw.get("alpine_packages", ["curl", "bash", "nodejs", "npm", "ripgrep"]), "defaults.alpine_packages"),
        docker_network_pool_cidr=_optional_str(defaults_raw.get("docker_network_pool_cidr")),
        docker_network_subnet_prefix=_optional_positive_int(defaults_raw.get("docker_network_subnet_prefix"), "defaults.docker_network_subnet_prefix"),
        tasks=_string_list(defaults_raw.get("tasks", []), "defaults.tasks"),
    )
    matrix = MatrixConfig(path=path, defaults=defaults, models=[_model_entry(item, idx) for idx, item in enumerate(models_raw)])
    validate_matrix(matrix, check_env=False)
    return matrix


def validate_matrix(matrix: MatrixConfig, *, check_env: bool) -> None:
    ids: set[str] = set()
    for model in matrix.models:
        if model.id in ids:
            raise ValueError(f"duplicate model id: {model.id}")
        ids.add(model.id)
        if check_env and model.api_key_env not in os.environ:
            raise ValueError(f"required env var is not set: {model.api_key_env}")
    _validate_docker_network_pool(matrix.defaults.docker_network_pool_cidr, matrix.defaults.docker_network_subnet_prefix)


def _model_entry(raw: Any, idx: int) -> ModelEntry:
    obj = _mapping(raw, f"models[{idx}]")
    return ModelEntry(
        id=str(_required(obj, "id", f"models[{idx}]")),
        model_slug=str(_required(obj, "model_slug", f"models[{idx}]")),
        provider_id=str(_required(obj, "provider_id", f"models[{idx}]")),
        provider_name=str(_required(obj, "provider_name", f"models[{idx}]")),
        api_key_env=str(_required(obj, "api_key_env", f"models[{idx}]")),
        base_url=str(_required(obj, "base_url", f"models[{idx}]")),
        context_window=_optional_positive_int(obj.get("context_window"), f"models[{idx}].context_window"),
        max_output_tokens=_optional_positive_int(obj.get("max_output_tokens"), f"models[{idx}].max_output_tokens"),
        extra_env=_string_mapping(obj.get("extra_env", {}), f"models[{idx}].extra_env"),
    )


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _string_mapping(value: Any, name: str) -> dict[str, str]:
    obj = _mapping(value, name)
    return {str(key): str(val) for key, val in obj.items()}


def _required(obj: dict[str, Any], key: str, name: str) -> Any:
    if key not in obj or obj[key] in (None, ""):
        raise ValueError(f"{name}.{key} is required")
    return obj[key]


def _required_str(value: Any, name: str) -> str:
    if value in (None, ""):
        raise ValueError(f"{name} is required")
    return str(value)


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_docker_network_pool(pool_cidr: str | None, subnet_prefix: int | None) -> None:
    if pool_cidr is None:
        if subnet_prefix is not None:
            raise ValueError("defaults.docker_network_subnet_prefix requires defaults.docker_network_pool_cidr")
        return
    import ipaddress

    try:
        pool = ipaddress.ip_network(pool_cidr)
    except ValueError as exc:
        raise ValueError("defaults.docker_network_pool_cidr must be a valid CIDR") from exc
    prefix = subnet_prefix if subnet_prefix is not None else 24
    if prefix < pool.prefixlen:
        raise ValueError("defaults.docker_network_subnet_prefix must be >= docker_network_pool_cidr prefix")
    if prefix > 30:
        raise ValueError("defaults.docker_network_subnet_prefix must be <= 30")


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [str(item) for item in value]
