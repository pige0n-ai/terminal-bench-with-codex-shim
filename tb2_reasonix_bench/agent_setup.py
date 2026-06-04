from __future__ import annotations

import shlex


def config_toml(
    *,
    provider_name: str,
    model_slug: str,
    api_key_env: str,
    base_url: str,
    auto_plan: str,
    planner_model: str | None,
    subagent_model: str | None,
    permissions_mode: str,
) -> str:
    lines = [
        f'default_model = "{_toml_escape(provider_name)}"',
        "",
        "[agent]",
        f'auto_plan = "{_toml_escape(auto_plan)}"',
    ]
    if planner_model:
        lines.append(f'planner_model = "{_toml_escape(planner_model)}"')
    if subagent_model:
        lines.append(f'subagent_model = "{_toml_escape(subagent_model)}"')
    lines.extend(
        [
            "",
            "[[providers]]",
            f'name = "{_toml_escape(provider_name)}"',
            'kind = "openai"',
            f'base_url = "{_toml_escape(base_url)}"',
            f'model = "{_toml_escape(model_slug)}"',
            f'api_key_env = "{_toml_escape(api_key_env)}"',
            "",
            "[permissions]",
            f'mode = "{_toml_escape(permissions_mode)}"',
        ]
    )
    return "\n".join(lines) + "\n"


def setup_command(*, config_toml_text: str, agent_dir: str, config_dir: str) -> str:
    config_file = f"{config_dir.rstrip('/')}/config.toml"
    return (
        "set -euo pipefail\n"
        "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi\n"
        f"mkdir -p {shlex.quote(agent_dir)} {shlex.quote(config_dir)}\n"
        f"printf %s {shlex.quote(config_toml_text)} > {shlex.quote(config_file)}\n"
        f"cp {shlex.quote(config_file)} {shlex.quote(agent_dir)}/reasonix.toml\n"
        f"reasonix --version > {shlex.quote(agent_dir)}/reasonix-version.txt\n"
    )


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
