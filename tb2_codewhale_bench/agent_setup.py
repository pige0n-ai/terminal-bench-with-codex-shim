from __future__ import annotations

import shlex

from .provider_env import provider_env_names


def runtime_env(
    *,
    provider: str,
    api_key_env: str,
    api_key: str,
    base_url: str,
    model_slug: str,
    codewhale_home: str,
    stream_idle_timeout_secs: int | None,
) -> dict[str, str]:
    native_api_key_env, base_env, model_env = provider_env_names(provider)
    env = {
        "HOME": codewhale_home,
        "CODEWHALE_HOME": codewhale_home,
        "CODEWHALE_PROVIDER": provider,
        "DEEPSEEK_PROVIDER": provider,
        api_key_env: api_key,
        native_api_key_env: api_key,
        base_env: base_url,
    }
    if model_env is not None:
        env[model_env] = model_slug
    if stream_idle_timeout_secs is not None:
        env["DEEPSEEK_STREAM_IDLE_TIMEOUT_SECS"] = str(stream_idle_timeout_secs)
    return env


def setup_command(*, agent_dir: str, codewhale_home: str) -> str:
    return (
        "set -euo pipefail\n"
        "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi\n"
        f"mkdir -p {shlex.quote(agent_dir)} {shlex.quote(codewhale_home)}\n"
        f"command -v codewhale > {shlex.quote(agent_dir)}/codewhale-bin.txt\n"
    )
