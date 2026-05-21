from __future__ import annotations

import shlex
from typing import Any

from .agent_setup import setup_command

from harbor.agents.installed.base import with_prompt_template
from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths


class ShimmedCodex(Codex):
    """Harbor Codex agent wired to a codex-shim custom model provider."""

    def __init__(
        self,
        *args,
        codex_shim_base_url: str,
        codex_model_provider: str = "codex_shim",
        context_window: int = 1_000_000,
        reasoning_effort: str = "xhigh",
        model_catalog_json: str = "",
        codex_cli_version: str = "0.131.0",
        node_version: str = "22",
        nvm_version: str = "0.40.2",
        root_packages: str | list[str] = "curl,ripgrep",
        alpine_packages: str | list[str] = "curl,bash,nodejs,npm,ripgrep",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.codex_shim_base_url = codex_shim_base_url
        self.codex_model_provider = codex_model_provider
        self.context_window = context_window
        self.reasoning_effort = reasoning_effort
        self.model_catalog_json = _required_text(model_catalog_json, "model_catalog_json")
        self.codex_cli_version = _required_text(codex_cli_version, "codex_cli_version")
        self.node_version = _required_text(node_version, "node_version")
        self.nvm_version = _required_text(nvm_version, "nvm_version")
        self.root_packages = _package_list(root_packages, "root_packages")
        self.alpine_packages = _package_list(alpine_packages, "alpine_packages")

    @staticmethod
    def name() -> str:
        return "ShimmedCodex"

    async def install(self, environment: BaseEnvironment) -> None:
        root_packages = " ".join(shlex.quote(package) for package in self.root_packages)
        alpine_packages = " ".join(shlex.quote(package) for package in self.alpine_packages)
        nvm_url = f"https://raw.githubusercontent.com/nvm-sh/nvm/v{self.nvm_version}/install.sh"
        version_spec = f"@{self.codex_cli_version}"

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
                f"  npm install -g @openai/codex{version_spec};"
                " else"
                f"  curl -o- {shlex.quote(nvm_url)} | bash &&"
                '  export NVM_DIR="$HOME/.nvm" &&'
                '  . "$NVM_DIR/nvm.sh" &&'
                "  command -v nvm &>/dev/null || { echo 'Error: NVM failed to load' >&2; exit 1; } &&"
                f"  nvm install {shlex.quote(self.node_version)} &&"
                f"  nvm alias default {shlex.quote(self.node_version)} && npm -v &&"
                f"  npm install -g @openai/codex{version_spec};"
                " fi && "
                "codex --version"
            ),
        )
        await self.exec_as_root(
            environment,
            command=(
                "for bin in node codex; do"
                '  BIN_PATH="$(which "$bin" 2>/dev/null || true)";'
                '  if [ -n "$BIN_PATH" ] && [ "$BIN_PATH" != "/usr/local/bin/$bin" ]; then'
                '    ln -sf "$BIN_PATH" "/usr/local/bin/$bin";'
                "  fi;"
                " done"
            ),
        )

    def _config_toml(self, model: str) -> str:
        catalog_path = self._REMOTE_CODEX_HOME.as_posix()
        provider = self.codex_model_provider
        return f"""model_provider = "{provider}"
model = "{model}"
model_catalog_json = "{catalog_path}/model-catalog-shim.json"
web_search = "disabled"
model_reasoning_effort = "{self.reasoning_effort}"
plan_mode_reasoning_effort = "{self.reasoning_effort}"

[model_providers.{provider}]
name = "codex-shim"
base_url = "{self.codex_shim_base_url}"
wire_api = "responses"
supports_websockets = false
"""

    def _health_url(self) -> str:
        base = self.codex_shim_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return f"{base}/healthz"

    @with_prompt_template
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        if not self.model_name:
            raise ValueError("Model name is required")

        model = self.model_name.split("/")[-1]
        escaped_instruction = shlex.quote(instruction)
        cli_flags = self.build_cli_flags()
        cli_flags_arg = (cli_flags + " ") if cli_flags else ""

        remote_codex_home = self._REMOTE_CODEX_HOME.as_posix()
        remote_secrets_dir = self._REMOTE_CODEX_SECRETS_DIR.as_posix()
        output_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME

        agent_dir = EnvironmentPaths.agent_dir.as_posix()

        env: dict[str, str] = {
            "CODEX_HOME": remote_codex_home,
            "OPENAI_API_KEY": "",
        }

        await self.exec_as_agent(
            environment,
            command=setup_command(
                config_toml=self._config_toml(model),
                remote_secrets_dir=remote_secrets_dir,
                agent_dir=agent_dir,
                model_catalog_json=self.model_catalog_json,
            ),
            env=env,
        )

        try:
            await self.exec_as_agent(
                environment,
                command=(
                    "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                    "codex exec "
                    "--dangerously-bypass-approvals-and-sandbox "
                    "--skip-git-repo-check "
                    "--json "
                    "--enable unified_exec "
                    f"{cli_flags_arg}"
                    "-- "
                    f"{escaped_instruction} "
                    f"2>&1 </dev/null | tee {output_path}"
                ),
                env=env,
            )
        finally:
            try:
                await self.exec_as_agent(
                    environment,
                    command=(
                        f"mkdir -p {agent_dir}\n"
                        'if [ -d "$CODEX_HOME/sessions" ]; then\n'
                        f"  rm -rf {(EnvironmentPaths.agent_dir / 'sessions').as_posix()}\n"
                        f'  cp -R "$CODEX_HOME/sessions" '
                        f"{(EnvironmentPaths.agent_dir / 'sessions').as_posix()}\n"
                        "fi"
                    ),
                    env=env,
                )
            except Exception:
                pass

            try:
                await self.exec_as_agent(
                    environment,
                    command=f'rm -rf {shlex.quote(remote_secrets_dir)} "$CODEX_HOME"',
                    env=env,
                )
            except Exception:
                pass



def _required_text(value: Any, name: str) -> str:
    parsed = str(value)
    if not parsed:
        raise ValueError(f"{name} is required")
    return parsed


def _package_list(value: str | list[str], name: str) -> list[str]:
    if isinstance(value, str):
        packages = [item.strip() for item in value.split(",")]
    else:
        packages = [str(item).strip() for item in value]
    packages = [item for item in packages if item]
    if not packages:
        raise ValueError(f"{name} must contain at least one package")
    return packages


CodexShimAgent = ShimmedCodex
