from __future__ import annotations

import shlex
from typing import Any

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment


class PinnedClaudeCode(ClaudeCode):
    """Claude Code agent that installs the CLI from npm at a pinned version."""

    def __init__(
        self,
        *args,
        node_version: str = "22",
        nvm_version: str = "0.40.2",
        root_packages: str | list[str] = "curl,ripgrep",
        alpine_packages: str | list[str] = "curl,bash,nodejs,npm,ripgrep",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.node_version = _required_text(node_version, "node_version")
        self.nvm_version = _required_text(nvm_version, "nvm_version")
        self.root_packages = _package_list(root_packages, "root_packages")
        self.alpine_packages = _package_list(alpine_packages, "alpine_packages")

    async def install(self, environment: BaseEnvironment) -> None:
        root_packages = " ".join(shlex.quote(package) for package in self.root_packages)
        alpine_packages = " ".join(shlex.quote(package) for package in self.alpine_packages)
        nvm_url = f"https://raw.githubusercontent.com/nvm-sh/nvm/v{self.nvm_version}/install.sh"
        version_spec = f"@{self._version}" if self._version else "@latest"

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
                f"  npm install -g @anthropic-ai/claude-code{version_spec};"
                " else"
                f"  curl -o- {shlex.quote(nvm_url)} | bash &&"
                '  export NVM_DIR="$HOME/.nvm" &&'
                '  . "$NVM_DIR/nvm.sh" &&'
                "  command -v nvm &>/dev/null || { echo 'Error: NVM failed to load' >&2; exit 1; } &&"
                f"  nvm install {shlex.quote(self.node_version)} &&"
                f"  nvm alias default {shlex.quote(self.node_version)} && npm -v &&"
                f"  npm install -g @anthropic-ai/claude-code{version_spec};"
                " fi && "
                'mkdir -p "$HOME/.local/bin" && '
                "for bin in node npm claude; do "
                '  BIN_PATH="$(command -v "$bin")" && '
                '  ln -sf "$BIN_PATH" "$HOME/.local/bin/$bin"; '
                "done && "
                "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc && "
                "claude --version"
            ),
        )
        await self.exec_as_root(
            environment,
            command=(
                "for bin in node npm claude; do"
                '  BIN_PATH="$(which "$bin" 2>/dev/null || true)";'
                '  if [ -n "$BIN_PATH" ] && [ "$BIN_PATH" != "/usr/local/bin/$bin" ]; then'
                '    ln -sf "$BIN_PATH" "/usr/local/bin/$bin";'
                "  fi;"
                " done"
            ),
        )


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
