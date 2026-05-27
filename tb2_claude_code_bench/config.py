from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


THINKING_VALUES = {"enabled", "adaptive", "disabled"}
THINKING_DISPLAY_VALUES = {"summarized", "omitted"}
REASONING_EFFORT_VALUES = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class Defaults:
    harbor_bin: str = "harbor"
    harbor_dataset: str = "terminal-bench/terminal-bench-2-1"
    harbor_jobs_dir: Path = Path("runs")
    harbor_n_attempts: int = 1
    harbor_n_concurrent: int = 1
    claude_code_version: str = "2.1.144"
    temperature: float | None = None
    top_p: float | None = None
    thinking: str | None = None
    reasoning_effort: str | None = None
    thinking_display: str | None = "omitted"
    max_thinking_tokens: int | None = None
    max_turns: int | None = None
    max_budget_usd: str | None = None
    fallback_model: str | None = None
    allowed_tools: str | None = None
    disallowed_tools: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)
    extra_env: dict[str, str] = field(default_factory=dict)
    tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelEntry:
    id: str
    model_slug: str
    api_key_env: str
    anthropic_base_url: str
    temperature: float | None = None
    top_p: float | None = None
    thinking: str | None = None
    reasoning_effort: str | None = None
    thinking_display: str | None = None
    max_thinking_tokens: int | None = None
    max_turns: int | None = None
    max_budget_usd: str | None = None
    fallback_model: str | None = None
    allowed_tools: str | None = None
    disallowed_tools: str | None = None
    extra_body: dict[str, Any] | None = None
    extra_env: dict[str, str] | None = None

    def resolved_extra_body(self, defaults: Defaults) -> dict[str, Any]:
        body: dict[str, Any] = dict(defaults.extra_body)
        if self.extra_body:
            body.update(self.extra_body)
        temperature = self.temperature if self.temperature is not None else defaults.temperature
        top_p = self.top_p if self.top_p is not None else defaults.top_p
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        return body

    def resolved_extra_env(self, defaults: Defaults) -> dict[str, str]:
        env = dict(defaults.extra_env)
        if self.extra_env:
            env.update(self.extra_env)
        extra_body = self.resolved_extra_body(defaults)
        if extra_body:
            import json

            env["CLAUDE_CODE_EXTRA_BODY"] = json.dumps(extra_body, separators=(",", ":"), sort_keys=True)
        return env

    def resolved_metadata(self, defaults: Defaults) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_slug": self.model_slug,
            "api_key_env": self.api_key_env,
            "anthropic_base_url": self.anthropic_base_url,
            "claude_code_version": defaults.claude_code_version,
            "thinking": self.thinking or defaults.thinking,
            "reasoning_effort": self.reasoning_effort or defaults.reasoning_effort,
            "thinking_display": self.thinking_display or defaults.thinking_display,
            "max_thinking_tokens": self.max_thinking_tokens or defaults.max_thinking_tokens,
            "max_turns": self.max_turns or defaults.max_turns,
            "allowed_tools": self.allowed_tools or defaults.allowed_tools,
            "disallowed_tools": self.disallowed_tools or defaults.disallowed_tools,
            "extra_body": self.resolved_extra_body(defaults),
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
        claude_code_version=_required_str(defaults_raw.get("claude_code_version", "2.1.144"), "defaults.claude_code_version"),
        temperature=_optional_float_range(defaults_raw.get("temperature"), "defaults.temperature", 0.0, 2.0),
        top_p=_optional_float_range(defaults_raw.get("top_p"), "defaults.top_p", 0.0, 1.0),
        thinking=_optional_enum(defaults_raw.get("thinking"), "defaults.thinking", THINKING_VALUES),
        reasoning_effort=_optional_enum(defaults_raw.get("reasoning_effort"), "defaults.reasoning_effort", REASONING_EFFORT_VALUES),
        thinking_display=_optional_enum(defaults_raw.get("thinking_display", "omitted"), "defaults.thinking_display", THINKING_DISPLAY_VALUES),
        max_thinking_tokens=_optional_positive_int(defaults_raw.get("max_thinking_tokens"), "defaults.max_thinking_tokens"),
        max_turns=_optional_positive_int(defaults_raw.get("max_turns"), "defaults.max_turns"),
        max_budget_usd=_optional_str(defaults_raw.get("max_budget_usd")),
        fallback_model=_optional_str(defaults_raw.get("fallback_model")),
        allowed_tools=_optional_str(defaults_raw.get("allowed_tools")),
        disallowed_tools=_optional_str(defaults_raw.get("disallowed_tools")),
        extra_body=_optional_mapping(defaults_raw.get("extra_body"), "defaults.extra_body") or {},
        extra_env=_string_mapping(defaults_raw.get("extra_env", {}), "defaults.extra_env"),
        tasks=_string_list(defaults_raw.get("tasks", []), "defaults.tasks"),
    )
    models = [_model_entry(item, idx) for idx, item in enumerate(models_raw)]
    matrix = MatrixConfig(path=path, defaults=defaults, models=models)
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
        api_key_env=str(_required(obj, "api_key_env", f"models[{idx}]")),
        anthropic_base_url=str(_required(obj, "anthropic_base_url", f"models[{idx}]")),
        temperature=_optional_float_range(obj.get("temperature"), f"models[{idx}].temperature", 0.0, 2.0),
        top_p=_optional_float_range(obj.get("top_p"), f"models[{idx}].top_p", 0.0, 1.0),
        thinking=_optional_enum(obj.get("thinking"), f"models[{idx}].thinking", THINKING_VALUES),
        reasoning_effort=_optional_enum(obj.get("reasoning_effort"), f"models[{idx}].reasoning_effort", REASONING_EFFORT_VALUES),
        thinking_display=_optional_enum(obj.get("thinking_display"), f"models[{idx}].thinking_display", THINKING_DISPLAY_VALUES),
        max_thinking_tokens=_optional_positive_int(obj.get("max_thinking_tokens"), f"models[{idx}].max_thinking_tokens"),
        max_turns=_optional_positive_int(obj.get("max_turns"), f"models[{idx}].max_turns"),
        max_budget_usd=_optional_str(obj.get("max_budget_usd")),
        fallback_model=_optional_str(obj.get("fallback_model")),
        allowed_tools=_optional_str(obj.get("allowed_tools")),
        disallowed_tools=_optional_str(obj.get("disallowed_tools")),
        extra_body=_optional_mapping(obj.get("extra_body"), f"models[{idx}].extra_body"),
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


def _optional_mapping(value: Any, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, name)


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


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _optional_float_range(value: Any, name: str, minimum: float, maximum: float) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def _optional_enum(value: Any, name: str, allowed: set[str]) -> str | None:
    if value in (None, ""):
        return None
    parsed = str(value).strip().lower()
    if parsed not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return parsed


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [str(item) for item in value]
