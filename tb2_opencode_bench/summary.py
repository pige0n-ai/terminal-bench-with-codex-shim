from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NUMERIC_METRICS = [
    "n_requests",
    "n_turns",
    "n_tool_calls",
    "n_input_tokens",
    "n_cache_read_tokens",
    "n_cache_creation_tokens",
    "n_cache_tokens",
    "n_output_tokens",
    "n_reasoning_tokens",
    "n_total_tokens",
    "cost_usd",
    "wall_time_sec",
    "agent_time_sec",
    "verifier_time_sec",
]


def summarize_run(run_dir: Path) -> dict[str, Any]:
    jobs_dir = run_dir / "jobs"
    trials = []
    for result_path in sorted(jobs_dir.glob("*/*/result.json")):
        data = _read_json(result_path)
        trials.append(_summarize_trial(result_path, data))

    by_model: dict[str, dict[str, Any]] = {}
    for trial in trials:
        model = trial["model"] or "unknown"
        bucket = by_model.setdefault(
            model,
            {
                "model": model,
                "n_trials": 0,
                "n_passed": 0,
                "n_failed": 0,
                "n_errored": 0,
                "n_cancelled": 0,
                **{key: None for key in NUMERIC_METRICS},
                "metric_counts": {key: 0 for key in NUMERIC_METRICS},
                "failure_categories": {},
            },
        )
        bucket["n_trials"] += 1
        if trial["status"] == "passed":
            bucket["n_passed"] += 1
        elif trial["status"] == "cancelled":
            bucket["n_cancelled"] += 1
        elif trial["status"] == "errored":
            bucket["n_errored"] += 1
        else:
            bucket["n_failed"] += 1
        for key in NUMERIC_METRICS:
            if trial.get(key) is not None:
                bucket[key] = (bucket[key] or 0) + trial[key]
                bucket["metric_counts"][key] += 1
        category = trial.get("failure_category")
        if category:
            bucket["failure_categories"][category] = bucket["failure_categories"].get(category, 0) + 1

    return {
        "run_dir": str(run_dir),
        "n_trials": len(trials),
        "models": list(by_model.values()),
        "trials": trials,
    }


def write_summary(run_dir: Path) -> dict[str, Any]:
    summary = summarize_run(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    _write_csv(run_dir / "summary.csv", summary["trials"])
    return summary


def _summarize_trial(result_path: Path, data: dict[str, Any]) -> dict[str, Any]:
    verifier = data.get("verifier_result") or {}
    agent = data.get("agent_result") or {}
    exception = data.get("exception_info") or {}
    model_info = (data.get("agent_info") or {}).get("model_info") or {}

    status = "failed"
    reward = verifier.get("reward")
    if reward is None and isinstance(verifier.get("rewards"), dict):
        reward = verifier["rewards"].get("reward")
    if exception:
        status = "cancelled" if exception.get("exception_type") == "CancelledError" else "errored"
    elif reward == 1 or reward == 1.0:
        status = "passed"
    elif verifier:
        status = "failed"
    else:
        status = "errored"

    exception_type = exception.get("exception_type")
    metrics = _trial_metrics(result_path, data, agent, verifier)
    return {
        "result_path": str(result_path),
        "task_name": data.get("task_name"),
        "trial_name": data.get("trial_name"),
        "model": model_info.get("name"),
        "status": status,
        "reward": reward,
        "exception_type": exception_type,
        "failure_category": _failure_category(result_path, exception_type),
        **metrics,
    }


def _trial_metrics(result_path: Path, data: dict[str, Any], agent: dict[str, Any], verifier: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _first_number(agent, "n_input_tokens", "input_tokens", "prompt_tokens", "usage.input_tokens", "usage.prompt_tokens")
    output_tokens = _first_number(agent, "n_output_tokens", "output_tokens", "completion_tokens", "usage.output_tokens", "usage.completion_tokens")
    cache_read_tokens = _first_number(agent, "n_cache_read_tokens", "cache_read_tokens", "cache_read_input_tokens", "prompt_cache_hit_tokens", "usage.cache_read_input_tokens", "usage.prompt_cache_hit_tokens")
    cache_creation_tokens = _first_number(agent, "n_cache_creation_tokens", "cache_creation_tokens", "cache_creation_input_tokens", "prompt_cache_miss_tokens", "usage.cache_creation_input_tokens", "usage.prompt_cache_miss_tokens")
    cache_tokens = _first_number(agent, "n_cache_tokens", "cache_tokens", "cached_tokens", "usage.cache_tokens", "usage.cached_tokens")
    if cache_tokens is None:
        cache_tokens = _sum_optional(cache_read_tokens, cache_creation_tokens)
    reasoning_tokens = _first_number(agent, "n_reasoning_tokens", "reasoning_tokens", "usage.reasoning_tokens", "usage.completion_tokens_details.reasoning_tokens", "usage.output_tokens_details.reasoning_tokens")
    total_tokens = _first_number(agent, "n_total_tokens", "total_tokens", "usage.total_tokens")
    if total_tokens is None:
        total_tokens = _sum_optional(input_tokens, output_tokens)

    return {
        "n_requests": _first_number(agent, "n_requests", "request_count", "num_requests", "requests"),
        "n_turns": _first_number(agent, "n_turns", "turn_count", "num_turns", "iterations", "n_iterations"),
        "n_tool_calls": _first_number(agent, "n_tool_calls", "tool_call_count", "num_tool_calls"),
        "n_input_tokens": input_tokens,
        "n_cache_read_tokens": cache_read_tokens,
        "n_cache_creation_tokens": cache_creation_tokens,
        "n_cache_tokens": cache_tokens,
        "n_output_tokens": output_tokens,
        "n_reasoning_tokens": reasoning_tokens,
        "n_total_tokens": total_tokens,
        "cost_usd": _first_number(agent, "cost_usd", "cost", "total_cost_usd"),
        "wall_time_sec": _duration_seconds(data, result_path=result_path),
        "agent_time_sec": _duration_seconds(agent),
        "verifier_time_sec": _duration_seconds(verifier),
    }


def _failure_category(result_path: Path, exception_type: str | None) -> str | None:
    if not exception_type:
        return None
    trial_dir = result_path.parent
    text_parts = []
    for path in [trial_dir / "agent" / "opencode.txt", trial_dir / "trial.log"]:
        if path.exists():
            text_parts.append(path.read_text(errors="replace"))
    lowered = "\n".join(text_parts).lower()

    if "model-catalog-shim.json` as json: eof" in lowered:
        return "opencode_catalog_empty"
    if "failed to parse model_catalog_json" in lowered:
        return "opencode_catalog_invalid"
    if "stream disconnected before completion" in lowered:
        return "agent_stream_failed"
    if "response.failed event received" in lowered:
        return "agent_response_failed"
    if "command failed" in lowered and "opencode run" not in lowered:
        return "setup_failed"
    if exception_type == "AgentTimeoutError":
        return "agent_timeout"
    if exception_type == "NonZeroAgentExitCodeError":
        return "agent_nonzero"
    return exception_type


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "task_name",
        "trial_name",
        "model",
        "status",
        "reward",
        "exception_type",
        "failure_category",
        "n_input_tokens",
        "n_cache_read_tokens",
        "n_cache_creation_tokens",
        "n_cache_tokens",
        "n_output_tokens",
        "n_reasoning_tokens",
        "n_total_tokens",
        "n_requests",
        "n_turns",
        "n_tool_calls",
        "cost_usd",
        "wall_time_sec",
        "agent_time_sec",
        "verifier_time_sec",
        "result_path",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return {
            "task_name": None,
            "trial_name": path.parent.name,
            "agent_info": {"model_info": {"name": "unknown"}},
            "agent_result": {},
            "verifier_result": {},
            "exception_info": {"exception_type": f"summary_read_error:{type(exc).__name__}"},
        }
    if not isinstance(data, dict):
        return {
            "task_name": None,
            "trial_name": path.parent.name,
            "agent_info": {"model_info": {"name": "unknown"}},
            "agent_result": {},
            "verifier_result": {},
            "exception_info": {"exception_type": "summary_read_error:non_object_json"},
        }
    return data


def _first_number(obj: dict[str, Any], *paths: str) -> int | float | None:
    for path in paths:
        value = _lookup(obj, path)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                continue
    return None


def _lookup(obj: dict[str, Any], path: str) -> Any:
    current: Any = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _sum_optional(*values: int | float | None) -> int | float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known)


def _duration_seconds(obj: dict[str, Any], *, result_path: Path | None = None) -> int | float | None:
    direct = _first_number(
        obj,
        "wall_time_sec",
        "wall_time_seconds",
        "agent_time_sec",
        "agent_time_seconds",
        "verifier_time_sec",
        "verifier_time_seconds",
        "duration_sec",
        "duration_seconds",
        "elapsed_sec",
        "elapsed_seconds",
        "runtime_sec",
        "runtime_seconds",
    )
    if direct is not None:
        return direct

    start = _first_datetime(obj, "started_at", "start_time", "created_at")
    end = _first_datetime(obj, "finished_at", "completed_at", "end_time")
    if start is not None and end is not None:
        return max(0.0, (end - start).total_seconds())

    if result_path is not None:
        config_path = result_path.parent / "config.json"
        if config_path.exists():
            try:
                return max(0.0, result_path.stat().st_mtime - config_path.stat().st_mtime)
            except OSError:
                return None
    return None


def _first_datetime(obj: dict[str, Any], *paths: str) -> datetime | None:
    for path in paths:
        value = _lookup(obj, path)
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
