from __future__ import annotations

import shlex
import os
from typing import Any

from .agent_setup import config_json, setup_command

from harbor.agents.installed.base import with_prompt_template
from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths


class PinnedOpenCode(Codex):
    _OUTPUT_FILENAME = "opencode.txt"

    def __init__(
        self,
        *args,
        opencode_version: str = "1.15.13",
        node_version: str = "22",
        nvm_version: str = "0.40.2",
        root_packages: str | list[str] = "curl,ripgrep",
        alpine_packages: str | list[str] = "curl,bash,nodejs,npm,ripgrep",
        provider_id: str,
        provider_name: str,
        api_key_env: str,
        base_url: str,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.opencode_version = _required_text(opencode_version, "opencode_version")
        self.node_version = _required_text(node_version, "node_version")
        self.nvm_version = _required_text(nvm_version, "nvm_version")
        self.root_packages = _package_list(root_packages, "root_packages")
        self.alpine_packages = _package_list(alpine_packages, "alpine_packages")
        self.provider_id = _required_text(provider_id, "provider_id")
        self.provider_name = _required_text(provider_name, "provider_name")
        self.api_key_env = _required_text(api_key_env, "api_key_env")
        self.base_url = _required_text(base_url, "base_url")
        self.context_window = _optional_int(context_window, "context_window")
        self.max_output_tokens = _optional_int(max_output_tokens, "max_output_tokens")

    @staticmethod
    def name() -> str:
        return "PinnedOpenCode"

    async def install(self, environment: BaseEnvironment) -> None:
        root_packages = " ".join(shlex.quote(package) for package in self.root_packages)
        alpine_packages = " ".join(shlex.quote(package) for package in self.alpine_packages)
        nvm_url = f"https://raw.githubusercontent.com/nvm-sh/nvm/v{self.nvm_version}/install.sh"
        version_spec = f"@{self.opencode_version}"
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
                f"  npm install -g opencode-ai{version_spec};"
                " else"
                f"  curl -o- {shlex.quote(nvm_url)} | bash &&"
                '  export NVM_DIR="$HOME/.nvm" &&'
                '  . "$NVM_DIR/nvm.sh" &&'
                "  command -v nvm &>/dev/null || { echo 'Error: NVM failed to load' >&2; exit 1; } &&"
                f"  nvm install {shlex.quote(self.node_version)} &&"
                f"  nvm alias default {shlex.quote(self.node_version)} && npm -v &&"
                f"  npm install -g opencode-ai{version_spec};"
                " fi && opencode --version"
            ),
        )
        await self.exec_as_root(environment, command=_link_bins_command(["node", "npm", "opencode"]))

    @with_prompt_template
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        if not self.model_name:
            raise ValueError("Model name is required")
        model = self.model_name.split("/", 1)[-1]
        agent_dir = EnvironmentPaths.agent_dir.as_posix()
        config_dir = f"{agent_dir}/opencode-config"
        data_dir = f"{agent_dir}/opencode-data"
        output_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME
        config_text = config_json(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            model_slug=model,
            api_key_env=self.api_key_env,
            base_url=self.base_url,
            context_window=self.context_window,
            max_output_tokens=self.max_output_tokens,
        )
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ValueError(f"required env var is not set: {self.api_key_env}")
        env = {"OPENCODE_CONFIG": f"{config_dir}/opencode.json", "XDG_DATA_HOME": data_dir, self.api_key_env: api_key}
        await self.exec_as_agent(environment, command=setup_command(config_json_text=config_text, agent_dir=agent_dir, config_dir=config_dir, data_dir=data_dir), env=env)
        await self.exec_as_agent(
            environment,
            command=(
                "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                f"opencode run --model {shlex.quote(self.provider_id + '/' + model)} --format json "
                f"{shlex.quote(instruction)} 2>&1 </dev/null | tee {output_path}"
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


def _package_list(value: str | list[str], name: str) -> list[str]:
    packages = [item.strip() for item in value.split(",")] if isinstance(value, str) else [str(item).strip() for item in value]
    packages = [item for item in packages if item]
    if not packages:
        raise ValueError(f"{name} must contain at least one package")
    return packages
