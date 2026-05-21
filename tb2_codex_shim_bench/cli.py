from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import load_matrix, validate_matrix
from .harbor import run_harbor
from .shim import build_runtime, check_docker_reaches_shim, fetch_model_catalog_json, start_shim
from .summary import write_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tb2-codex-shim-bench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--matrix", type=Path, required=True)
    p_validate.add_argument("--check-env", action="store_true")
    p_validate.add_argument("--check-shim-bin", action="store_true")

    p_smoke = sub.add_parser("smoke")
    p_smoke.add_argument("--matrix", type=Path, required=True)
    p_smoke.add_argument("--model", required=True)
    p_smoke.add_argument("--task", required=True)
    p_smoke.add_argument("--run-name", default=None)
    p_smoke.add_argument("--skip-docker-health", action="store_true")

    p_run = sub.add_parser("run")
    p_run.add_argument("--matrix", type=Path, required=True)
    p_run.add_argument("--run-name", default=None)
    p_run.add_argument("--skip-docker-health", action="store_true")

    p_summary = sub.add_parser("summarize")
    p_summary.add_argument("--run-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args)
        if args.command == "smoke":
            return _smoke(args)
        if args.command == "run":
            return _run(args)
        if args.command == "summarize":
            return _summarize(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(args.command)


def _validate(args: argparse.Namespace) -> int:
    matrix = load_matrix(args.matrix)
    validate_matrix(matrix, check_files=args.check_shim_bin, check_env=args.check_env)
    print(f"ok: {len(matrix.models)} model(s) in {args.matrix}")
    return 0


def _smoke(args: argparse.Namespace) -> int:
    matrix = load_matrix(args.matrix)
    model = matrix.model_by_id(args.model)
    run_name = args.run_name or f"smoke-{model.id}-{_timestamp()}"
    return _run_models(matrix, [model.id], [args.task], run_name, skip_docker_health=args.skip_docker_health)


def _run(args: argparse.Namespace) -> int:
    matrix = load_matrix(args.matrix)
    run_name = args.run_name or f"run-{_timestamp()}"
    tasks = matrix.defaults.tasks
    return _run_models(matrix, [model.id for model in matrix.models], tasks, run_name, skip_docker_health=args.skip_docker_health)


def _summarize(args: argparse.Namespace) -> int:
    summary = write_summary(args.run_dir)
    print(json.dumps(summary["models"], indent=2, sort_keys=True))
    return 0


def _run_models(
    matrix,
    model_ids: list[str],
    tasks: list[str],
    run_name: str,
    *,
    skip_docker_health: bool,
) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    run_dir = matrix.defaults.harbor_jobs_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    jobs_root = run_dir / "jobs"
    resolved = {
        "run_name": run_name,
        "dataset": matrix.defaults.harbor_dataset,
        "tasks": tasks,
        "models": [],
        "harbor_results": [],
    }

    exit_code = 0
    for model_id in model_ids:
        model = matrix.model_by_id(model_id)
        runtime = build_runtime(matrix.defaults, model, run_dir)
        resolved["models"].append(
            {
                "id": model.id,
                "provider_profile": model.provider_profile,
                "model_slug": model.model_slug,
                "port": model.port,
                "config_path": str(runtime.config_path),
                "log_path": str(runtime.log_path),
                "codex_base_url": runtime.base_url_for_codex,
            }
        )
        print(f"starting shim for {model.id} on port {model.port}")
        shim = start_shim(matrix.defaults, runtime)
        try:
            if not skip_docker_health:
                check_docker_reaches_shim(matrix.defaults.docker_host, model.port)
            model_catalog_json = fetch_model_catalog_json(runtime)
            task_groups = [[task] for task in tasks] if tasks else [[]]
            for task_group in task_groups:
                task_suffix = f"-{_safe_slug(task_group[0])}" if task_group else "-full"
                job_name = f"{run_name}-{model.id}{task_suffix}"
                result = run_harbor(
                    defaults=matrix.defaults,
                    model=model,
                    codex_shim_base_url=runtime.base_url_for_codex,
                    model_catalog_json=model_catalog_json,
                    jobs_dir=jobs_root,
                    job_name=job_name,
                    tasks=task_group,
                    repo_root=repo_root,
                )
                harbor_log = run_dir / f"harbor-{model.id}{task_suffix}.log"
                harbor_log.write_text(result.stdout)
                resolved["harbor_results"].append(
                    {
                        "model_id": model.id,
                        "tasks": task_group,
                        "return_code": result.return_code,
                        "command": result.command,
                        "log_path": str(harbor_log),
                    }
                )
                if result.return_code != 0:
                    exit_code = 1
                    print(result.stdout, file=sys.stderr)
        finally:
            shim.stop()

    (run_dir / "matrix.resolved.json").write_text(json.dumps(resolved, indent=2, sort_keys=True))
    write_summary(run_dir)
    print(f"wrote run outputs to {run_dir}")
    return exit_code


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
