from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import Defaults, ModelEntry


@dataclass(frozen=True)
class ShimRuntime:
    model: ModelEntry
    config_path: Path
    log_path: Path
    base_url_for_codex: str
    health_url: str


class ShimProcess:
    def __init__(self, runtime: ShimRuntime, process: subprocess.Popen[str]):
        self.runtime = runtime
        self.process = process

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


def render_shim_config(defaults: Defaults, model: ModelEntry) -> dict:
    context_window = model.context_window or defaults.context_window
    reasoning_effort = model.reasoning_effort or defaults.reasoning_effort
    reasoning_enabled = defaults.reasoning_enabled if model.reasoning_enabled is None else model.reasoning_enabled
    reasoning_levels = model.reasoning_levels or [reasoning_effort]

    profile_config: dict = {"profile": model.provider_profile}
    if model.capabilities:
        profile_config["capabilities"] = model.capabilities
    if model.extra_body:
        profile_config["extra_body"] = model.extra_body

    config: dict = {
        "server": {
            "listen": f"{defaults.listen_host}:{model.port}",
            "base_path": "/v1",
        },
        "upstream": {
            "api_key_env": model.api_key_env,
        },
        "provider": {
            "profile_config": profile_config,
        },
        "reasoning": {
            "enabled": reasoning_enabled,
            "effort": reasoning_effort,
        },
        "models": {
            "default": model.model_slug,
            "catalog": [
                {
                    "slug": model.model_slug,
                    "context_window": context_window,
                    "reasoning_levels": reasoning_levels,
                }
            ],
        },
        "state": {
            "backend": defaults.state_backend,
        },
        "logging": {
            "level": defaults.logging_level,
        },
    }
    if model.upstream_base_url:
        config["upstream"]["base_url"] = model.upstream_base_url
    return config


def write_shim_config(defaults: Defaults, model: ModelEntry, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{model.id}.yaml"
    path.write_text(yaml.safe_dump(render_shim_config(defaults, model), sort_keys=False))
    return path


def build_runtime(defaults: Defaults, model: ModelEntry, run_dir: Path) -> ShimRuntime:
    config_path = write_shim_config(defaults, model, run_dir / "generated")
    log_path = run_dir / "shim-logs" / f"{model.id}.log"
    base_url = f"http://{defaults.docker_host}:{model.port}/v1"
    health_url = f"http://127.0.0.1:{model.port}/healthz"
    return ShimRuntime(
        model=model,
        config_path=config_path,
        log_path=log_path,
        base_url_for_codex=base_url,
        health_url=health_url,
    )


def start_shim(defaults: Defaults, runtime: ShimRuntime, timeout_sec: int = 30) -> ShimProcess:
    ensure_health_absent(runtime.health_url)
    runtime.log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    with runtime.log_path.open("w") as log_file:
        process = subprocess.Popen(
            [
                str(defaults.codex_shim_bin),
                "--config",
                str(runtime.config_path),
                "--listen",
                f"{defaults.listen_host}:{runtime.model.port}",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    shim = ShimProcess(runtime, process)
    try:
        wait_for_health(runtime.health_url, timeout_sec=timeout_sec)
    except Exception:
        shim.stop()
        raise
    return shim


def ensure_health_absent(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError:
        return
    raise RuntimeError(f"refusing to start shim because a service already responds at {url}: {body}")


def wait_for_health(url: str, timeout_sec: int) -> None:
    deadline = time.time() + timeout_sec
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("status") == "ok":
                    return
                raise RuntimeError(f"unexpected health response from {url}: {body}")
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"shim did not become healthy at {url}: {last_error}")


def check_docker_reaches_shim(docker_host: str, port: int, timeout_sec: int = 10) -> None:
    url = f"http://{docker_host}:{port}/healthz"
    deadline = time.time() + timeout_sec
    last_output = ""
    while time.time() < deadline:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "curlimages/curl:8.10.1",
                "-sS",
                "--max-time",
                "3",
                url,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        last_output = result.stdout
        if result.returncode == 0:
            try:
                body = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid Docker shim health response at {url}: {result.stdout}") from exc
            if body.get("status") == "ok":
                return
            raise RuntimeError(f"unexpected Docker shim health response at {url}: {body}")
        time.sleep(0.75)
    raise RuntimeError(f"Docker container cannot reach shim at {url}:\n{last_output}")
