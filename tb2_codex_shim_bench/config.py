from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


KNOWN_PROVIDER_PROFILES = {
    "deepseek-chat",
    "minimax-chat",
    "moonshot-chat",
    "zai-chat",
    "gemini-chat",
    "vertex-chat",
    "alibaba-chat",
    "alibaba-responses",
    "fireworks-chat",
    "fireworks-responses",
    "xai-chat",
    "xai-responses",
    "bedrock-chat",
    "bedrock-responses",
    "openrouter-chat",
    "openrouter-responses",
    "groq-chat",
    "groq-responses",
    "together-chat",
    "ollama-chat",
    "ollama-responses",
    "llamacpp-chat",
    "llamacpp-responses",
    "vllm-chat",
    "vllm-responses",
    "sglang-chat",
    "generic-chat",
}

BOOLEAN_CAPABILITY_FIELDS = {
    "supports_function_tools",
    "supports_parallel_tool_calls",
    "supports_structured_outputs",
    "supports_json_object",
    "supports_json_schema",
    "supports_vision_input",
    "supports_hosted_web_search",
    "supports_hosted_file_search",
    "supports_code_interpreter",
    "supports_previous_response_id",
    "supports_reasoning_effort",
    "request_stream_usage",
    "reliable_stream_usage_for_compaction",
    "supports_usage_in_stream_final",
}


@dataclass(frozen=True)
class Defaults:
    codex_shim_bin: Path
    listen_host: str = "0.0.0.0"
    docker_host: str = "host.docker.internal"
    harbor_bin: str = "harbor"
    harbor_dataset: str = "terminal-bench@2.0"
    harbor_jobs_dir: Path = Path("runs")
    harbor_n_attempts: int = 1
    harbor_n_concurrent: int = 1
    reasoning_enabled: bool = True
    reasoning_effort: str = "xhigh"
    context_window: int = 1_000_000
    state_backend: str = "memory"
    logging_level: str = "info"
    tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelEntry:
    id: str
    provider_profile: str
    model_slug: str
    api_key_env: str
    port: int
    upstream_base_url: str | None = None
    context_window: int | None = None
    reasoning_enabled: bool | None = None
    reasoning_effort: str | None = None
    reasoning_levels: list[str] | None = None
    capabilities: dict[str, bool] | None = None
    extra_body: dict[str, Any] | None = None
    harbor_model_name: str | None = None

    def codex_model(self) -> str:
        return self.harbor_model_name or self.model_slug


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
        codex_shim_bin=_resolve_path(base, _required(defaults_raw, "codex_shim_bin", "defaults")),
        listen_host=str(defaults_raw.get("listen_host", "0.0.0.0")),
        docker_host=str(defaults_raw.get("docker_host", "host.docker.internal")),
        harbor_bin=str(defaults_raw.get("harbor_bin", "harbor")),
        harbor_dataset=str(defaults_raw.get("harbor_dataset", "terminal-bench@2.0")),
        harbor_jobs_dir=_resolve_path(base, str(defaults_raw.get("harbor_jobs_dir", "runs"))),
        harbor_n_attempts=_positive_int(defaults_raw.get("harbor_n_attempts", 1), "defaults.harbor_n_attempts"),
        harbor_n_concurrent=_positive_int(defaults_raw.get("harbor_n_concurrent", 1), "defaults.harbor_n_concurrent"),
        reasoning_enabled=bool(defaults_raw.get("reasoning_enabled", True)),
        reasoning_effort=str(defaults_raw.get("reasoning_effort", "xhigh")),
        context_window=_positive_int(defaults_raw.get("context_window", 1_000_000), "defaults.context_window"),
        state_backend=str(defaults_raw.get("state_backend", "memory")),
        logging_level=str(defaults_raw.get("logging_level", "info")),
        tasks=_string_list(defaults_raw.get("tasks", []), "defaults.tasks"),
    )

    models = [_model_entry(item, idx) for idx, item in enumerate(models_raw)]
    matrix = MatrixConfig(path=path, defaults=defaults, models=models)
    validate_matrix(matrix, check_files=False, check_env=False)
    return matrix


def validate_matrix(matrix: MatrixConfig, *, check_files: bool, check_env: bool) -> None:
    ids: set[str] = set()
    ports: set[int] = set()
    for model in matrix.models:
        if model.id in ids:
            raise ValueError(f"duplicate model id: {model.id}")
        ids.add(model.id)

        if model.port in ports:
            raise ValueError(f"duplicate port: {model.port}")
        ports.add(model.port)

        if model.provider_profile not in KNOWN_PROVIDER_PROFILES:
            known = ", ".join(sorted(KNOWN_PROVIDER_PROFILES))
            raise ValueError(f"unknown provider_profile '{model.provider_profile}'. Known profiles: {known}")

        if check_env:
            import os

            if model.api_key_env and model.api_key_env not in os.environ:
                raise ValueError(f"required env var is not set: {model.api_key_env}")

    if check_files and not matrix.defaults.codex_shim_bin.is_file():
        raise ValueError(f"codex-shim binary not found: {matrix.defaults.codex_shim_bin}")


def _model_entry(raw: Any, idx: int) -> ModelEntry:
    obj = _mapping(raw, f"models[{idx}]")
    return ModelEntry(
        id=str(_required(obj, "id", f"models[{idx}]")),
        provider_profile=str(_required(obj, "provider_profile", f"models[{idx}]")),
        model_slug=str(_required(obj, "model_slug", f"models[{idx}]")),
        api_key_env=str(_required(obj, "api_key_env", f"models[{idx}]")),
        port=_positive_int(_required(obj, "port", f"models[{idx}]"), f"models[{idx}].port"),
        upstream_base_url=_optional_str(obj.get("upstream_base_url")),
        context_window=_optional_positive_int(obj.get("context_window"), f"models[{idx}].context_window"),
        reasoning_enabled=obj.get("reasoning_enabled") if obj.get("reasoning_enabled") is None else bool(obj.get("reasoning_enabled")),
        reasoning_effort=_optional_str(obj.get("reasoning_effort")),
        reasoning_levels=_optional_string_list(obj.get("reasoning_levels"), f"models[{idx}].reasoning_levels"),
        capabilities=_optional_bool_mapping(obj.get("capabilities"), f"models[{idx}].capabilities"),
        extra_body=obj.get("extra_body") if obj.get("extra_body") is None else _mapping(obj.get("extra_body"), f"models[{idx}].extra_body"),
        harbor_model_name=_optional_str(obj.get("harbor_model_name")),
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


def _required(obj: dict[str, Any], key: str, name: str) -> Any:
    if key not in obj or obj[key] in (None, ""):
        raise ValueError(f"{name}.{key} is required")
    return obj[key]


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


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [str(item) for item in value]


def _optional_string_list(value: Any, name: str) -> list[str] | None:
    if value is None:
        return None
    return _string_list(value, name)


def _optional_bool_mapping(value: Any, name: str) -> dict[str, bool] | None:
    if value is None:
        return None
    raw = _mapping(value, name)
    result: dict[str, bool] = {}
    for key, raw_value in raw.items():
        key = str(key)
        if key not in BOOLEAN_CAPABILITY_FIELDS:
            allowed = ", ".join(sorted(BOOLEAN_CAPABILITY_FIELDS))
            raise ValueError(
                f"{name}.{key} is not a supported boolean capability override. "
                f"Allowed: {allowed}"
            )
        if not isinstance(raw_value, bool):
            raise ValueError(f"{name}.{key} must be a boolean")
        result[key] = raw_value
    return result


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
