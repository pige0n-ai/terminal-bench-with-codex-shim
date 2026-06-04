from __future__ import annotations

import json
import shlex


def config_json(
    *,
    provider_id: str,
    provider_name: str,
    model_slug: str,
    api_key_env: str,
    base_url: str,
    context_window: int | None,
    max_output_tokens: int | None,
) -> str:
    model_config: dict[str, object] = {"name": model_slug}
    if context_window is not None or max_output_tokens is not None:
        limit: dict[str, int] = {}
        if context_window is not None:
            limit["context"] = context_window
        if max_output_tokens is not None:
            limit["output"] = max_output_tokens
        model_config["limit"] = limit

    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider_id}/{model_slug}",
        "enabled_providers": [provider_id],
        "permission": "allow",
        "provider": {
            provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider_name,
                "options": {
                    "baseURL": base_url,
                    "apiKey": f"{{env:{api_key_env}}}",
                },
                "models": {
                    model_slug: model_config,
                },
            },
        },
    }
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


def setup_command(*, config_json_text: str, agent_dir: str, config_dir: str, data_dir: str) -> str:
    config_file = f"{config_dir.rstrip('/')}/opencode.json"
    quoted_config = shlex.quote(config_json_text)
    return (
        "set -euo pipefail\n"
        "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi\n"
        f"mkdir -p {shlex.quote(agent_dir)} {shlex.quote(config_dir)} {shlex.quote(data_dir)}\n"
        f"printf %s {quoted_config} > {shlex.quote(config_file)}\n"
        f"cp {shlex.quote(config_file)} {shlex.quote(agent_dir)}/opencode.json\n"
        f"opencode --version > {shlex.quote(agent_dir)}/opencode-version.txt\n"
    )
