from __future__ import annotations

import os
import shlex
from typing import Any

from .agent_setup import runtime_env, setup_command

from harbor.agents.installed.base import with_prompt_template
from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths


class PinnedCodeWhale(Codex):
    _OUTPUT_FILENAME = "codewhale.txt"

    def __init__(
        self,
        *args,
        codewhale_version: str = "0.8.50",
        node_version: str = "22",
        nvm_version: str = "0.40.2",
        root_packages: str | list[str] = "curl,ripgrep",
        alpine_packages: str | list[str] = "curl,bash,nodejs,npm,ripgrep",
        provider: str,
        api_key_env: str,
        base_url: str,
        thinking: str | None = None,
        yolo: bool | str = True,
        stream_idle_timeout_secs: int | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.codewhale_version = _required_text(codewhale_version, "codewhale_version")
        self.node_version = _required_text(node_version, "node_version")
        self.nvm_version = _required_text(nvm_version, "nvm_version")
        self.root_packages = _package_list(root_packages, "root_packages")
        self.alpine_packages = _package_list(alpine_packages, "alpine_packages")
        self.provider = _required_text(provider, "provider")
        self.api_key_env = _required_text(api_key_env, "api_key_env")
        self.base_url = _required_text(base_url, "base_url")
        self.thinking = _optional_text(thinking)
        self.yolo = _bool(yolo, "yolo")
        self.stream_idle_timeout_secs = _optional_int(stream_idle_timeout_secs, "stream_idle_timeout_secs")

    @staticmethod
    def name() -> str:
        return "PinnedCodeWhale"

    async def install(self, environment: BaseEnvironment) -> None:
        root_packages = " ".join(shlex.quote(package) for package in self.root_packages)
        alpine_packages = " ".join(shlex.quote(package) for package in self.alpine_packages)
        nvm_url = f"https://raw.githubusercontent.com/nvm-sh/nvm/v{self.nvm_version}/install.sh"
        version_spec = f"@{self.codewhale_version}"
        await self.exec_as_root(
            environment,
            command=(
                "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then"
                f"  apk add --no-cache {alpine_packages};"
                " elif command -v apt-get &>/dev/null; then"
                f"  apt-get update && apt-get install -y {root_packages};"
                " elif command -v yum &>/dev/null; then"
                f"  yum install -y {root_packages};"
                " else"
                "  echo 'Error: no supported package manager found for pinned dependencies' >&2; exit 1;"
                " fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then"
                f"  npm install -g codewhale{version_spec};"
                " else"
                f"  curl -o- {shlex.quote(nvm_url)} | bash &&"
                '  export NVM_DIR="$HOME/.nvm" &&'
                '  . "$NVM_DIR/nvm.sh" &&'
                "  command -v nvm &>/dev/null || { echo 'Error: NVM failed to load' >&2; exit 1; } &&"
                f"  nvm install {shlex.quote(self.node_version)} &&"
                f"  nvm alias default {shlex.quote(self.node_version)} && npm -v &&"
                f"  npm install -g codewhale{version_spec};"
                " fi && codewhale --version"
            ),
        )
        await self.exec_as_root(environment, command=_link_bins_command(["node", "npm", "codewhale", "codewhale-tui"]))

    @with_prompt_template
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        if not self.model_name:
            raise ValueError("Model name is required")
        model_slug = self.model_name.split("/", 1)[-1]
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ValueError(f"required env var is not set: {self.api_key_env}")
        agent_dir = EnvironmentPaths.agent_dir.as_posix()
        codewhale_home = f"{agent_dir}/codewhale-home"
        output_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME
        env = runtime_env(
            provider=self.provider,
            api_key_env=self.api_key_env,
            api_key=api_key,
            base_url=self.base_url,
            model_slug=model_slug,
            codewhale_home=codewhale_home,
            stream_idle_timeout_secs=self.stream_idle_timeout_secs,
        )
        await self.exec_as_agent(environment, command=setup_command(agent_dir=agent_dir, codewhale_home=codewhale_home), env=env)
        cmd_parts = ["codewhale", "exec", "--auto", "--output-format", "stream-json", "--model", model_slug]
        if self.yolo:
            cmd_parts.insert(2, "--yolo")
        if self.thinking:
            cmd_parts.extend(["--thinking", self.thinking])
        cmd_parts.append(instruction)
        await self.exec_as_agent(
            environment,
            command=(
                "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                f"{' '.join(shlex.quote(part) for part in cmd_parts)} 2>&1 </dev/null | tee {output_path}"
            ),
            env=env,
        )


def _link_bins_command(bins: list[str]) -> str:
    joined = " ".join(shlex.quote(item) for item in bins)
    return (
        f"for bin in {joined}; do"
        '  BIN_PATH="$(which "$bin" 2>/dev/null || true)";'
        '  if [ -n "$BIN_PATH" ] && [ "$BIN_PATH" != "/usr/local/bin/$bin" ]; then'
        '    ln -sf "$BIN_PATH" "/usr/local/bin/$bin";'
        "  fi;"
        " done"
    )


def _required_text(value: Any, name: str) -> str:
    parsed = str(value)
    if not parsed:
        raise ValueError(f"{name} is required")
    return parsed


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"{name} must be a boolean")


def _package_list(value: str | list[str], name: str) -> list[str]:
    packages = [item.strip() for item in value.split(",")] if isinstance(value, str) else [str(item).strip() for item in value]
    packages = [item for item in packages if item]
    if not packages:
        raise ValueError(f"{name} must contain at least one package")
    return packages
