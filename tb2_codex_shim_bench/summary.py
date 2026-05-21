from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


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
                "n_input_tokens": 0,
                "n_cache_tokens": 0,
                "n_output_tokens": 0,
                "cost_usd": None,
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
        bucket["n_input_tokens"] += trial["n_input_tokens"] or 0
        bucket["n_cache_tokens"] += trial["n_cache_tokens"] or 0
        bucket["n_output_tokens"] += trial["n_output_tokens"] or 0
        if trial["cost_usd"] is not None:
            bucket["cost_usd"] = (bucket["cost_usd"] or 0.0) + trial["cost_usd"]
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
    return {
        "result_path": str(result_path),
        "task_name": data.get("task_name"),
        "trial_name": data.get("trial_name"),
        "model": model_info.get("name"),
        "status": status,
        "reward": reward,
        "exception_type": exception_type,
        "failure_category": _failure_category(result_path, exception_type),
        "n_input_tokens": agent.get("n_input_tokens"),
        "n_cache_tokens": agent.get("n_cache_tokens"),
        "n_output_tokens": agent.get("n_output_tokens"),
        "cost_usd": agent.get("cost_usd"),
    }


def _failure_category(result_path: Path, exception_type: str | None) -> str | None:
    if not exception_type:
        return None
    trial_dir = result_path.parent
    text_parts = []
    for path in [trial_dir / "agent" / "codex.txt", trial_dir / "trial.log"]:
        if path.exists():
            text_parts.append(path.read_text(errors="replace"))
    lowered = "\n".join(text_parts).lower()

    if "model-catalog-shim.json` as json: eof" in lowered:
        return "codex_catalog_empty"
    if "failed to parse model_catalog_json" in lowered:
        return "codex_catalog_invalid"
    if "stream disconnected before completion" in lowered:
        return "shim_stream_failed"
    if "response.failed event received" in lowered:
        return "shim_response_failed"
    if "command failed" in lowered and "codex exec" not in lowered:
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
        "n_cache_tokens",
        "n_output_tokens",
        "cost_usd",
        "result_path",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
