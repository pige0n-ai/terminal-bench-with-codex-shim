from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


AUTO_PLAN_VALUES = {"off", "ask", "on"}
PERMISSIONS_MODE_VALUES = {"allow", "ask", "deny"}


@dataclass(frozen=True)
class Defaults:
    harbor_bin: str = "harbor"
    harbor_dataset: str = "terminal-bench/terminal-bench-2-1"
    harbor_jobs_dir: Path = Path("runs")
    harbor_n_attempts: int = 1
    harbor_n_concurrent: int = 1
    reasonix_version: str = "1.0.0"
    node_version: str = "22"
    nvm_version: str = "0.40.2"
    root_packages: list[str] = field(default_factory=lambda: ["curl", "ripgrep"])
    alpine_packages: list[str] = field(default_factory=lambda: ["curl", "bash", "nodejs", "npm", "ripgrep"])
    auto_plan: str = "off"
    permissions_mode: str = "allow"
    tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelEntry:
    id: str
    model_slug: str
    provider_name: str
    api_key_env: str
    base_url: str
    auto_plan: str | None = None
    planner_model: str | None = None
    subagent_model: str | None = None
    permissions_mode: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    def reasonix_model(self) -> str:
        return self.provider_name

    def resolved_auto_plan(self, defaults: Defaults) -> str:
        return self.auto_plan or defaults.auto_plan

    def resolved_permissions_mode(self, defaults: Defaults) -> str:
        return self.permissions_mode or defaults.permissions_mode

    def resolved_metadata(self, defaults: Defaults) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_slug": self.model_slug,
            "provider_name": self.provider_name,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "reasonix_version": defaults.reasonix_version,
            "auto_plan": self.resolved_auto_plan(defaults),
            "planner_model": self.planner_model,
            "subagent_model": self.subagent_model,
            "permissions_mode": self.resolved_permissions_mode(defaults),
            "extra_env": dict(self.extra_env),
        }


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
        reasonix_version=_required_str(defaults_raw.get("reasonix_version", "1.0.0"), "defaults.reasonix_version"),
        node_version=_required_str(defaults_raw.get("node_version", "22"), "defaults.node_version"),
        nvm_version=_required_str(defaults_raw.get("nvm_version", "0.40.2"), "defaults.nvm_version"),
        root_packages=_string_list(defaults_raw.get("root_packages", ["curl", "ripgrep"]), "defaults.root_packages"),
        alpine_packages=_string_list(defaults_raw.get("alpine_packages", ["curl", "bash", "nodejs", "npm", "ripgrep"]), "defaults.alpine_packages"),
        auto_plan=_enum(defaults_raw.get("auto_plan", "off"), "defaults.auto_plan", AUTO_PLAN_VALUES),
        permissions_mode=_enum(defaults_raw.get("permissions_mode", "allow"), "defaults.permissions_mode", PERMISSIONS_MODE_VALUES),
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


def _model_entry(raw: Any, idx: int) -> ModelEntry:
    obj = _mapping(raw, f"models[{idx}]")
    return ModelEntry(
        id=str(_required(obj, "id", f"models[{idx}]")),
        model_slug=str(_required(obj, "model_slug", f"models[{idx}]")),
        provider_name=str(_required(obj, "provider_name", f"models[{idx}]")),
        api_key_env=str(_required(obj, "api_key_env", f"models[{idx}]")),
        base_url=str(_required(obj, "base_url", f"models[{idx}]")),
        auto_plan=_optional_enum(obj.get("auto_plan"), f"models[{idx}].auto_plan", AUTO_PLAN_VALUES),
        planner_model=_optional_str(obj.get("planner_model")),
        subagent_model=_optional_str(obj.get("subagent_model")),
        permissions_mode=_optional_enum(obj.get("permissions_mode"), f"models[{idx}].permissions_mode", PERMISSIONS_MODE_VALUES),
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


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _enum(value: Any, name: str, allowed: set[str]) -> str:
    parsed = _required_str(value, name)
    if parsed not in allowed:
        known = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {known}")
    return parsed


def _optional_enum(value: Any, name: str, allowed: set[str]) -> str | None:
    if value in (None, ""):
        return None
    return _enum(value, name, allowed)


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [str(item) for item in value]
