from __future__ import annotations

import shlex

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
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.codex_shim_base_url = codex_shim_base_url
        self.codex_model_provider = codex_model_provider
        self.context_window = context_window
        self.reasoning_effort = reasoning_effort

    @staticmethod
    def name() -> str:
        return "ShimmedCodex"

    def _config_toml(self, model: str) -> str:
        provider = self.codex_model_provider
        return f"""model_provider = "{provider}"
model = "{model}"
model_catalog_json = "{self._REMOTE_CODEX_HOME.as_posix()}/model-catalog-shim.json"
web_search = "disabled"
model_reasoning_effort = "{self.reasoning_effort}"
plan_mode_reasoning_effort = "{self.reasoning_effort}"

[model_providers.{provider}]
name = "codex-shim"
base_url = "{self.codex_shim_base_url}"
wire_api = "responses"
supports_websockets = false
"""

    def _model_catalog_json(self, model: str) -> str:
        return f"""{{
  "models": [
    {{
      "slug": "{model}",
      "display_name": "{model}",
      "description": "{model} via codex-shim",
      "default_reasoning_level": "{self.reasoning_effort}",
      "supported_reasoning_levels": [
        {{ "effort": "xhigh", "description": "" }},
        {{ "effort": "high", "description": "" }},
        {{ "effort": "medium", "description": "" }},
        {{ "effort": "low", "description": "" }}
      ],
      "context_window": {self.context_window},
      "max_context_window": {self.context_window},
      "effective_context_window_percent": 95,
      "shell_type": "unified_exec",
      "visibility": "list",
      "supported_in_api": true,
      "priority": 10,
      "supports_parallel_tool_calls": true,
      "input_modalities": ["text"],
      "default_reasoning_summary": "none",
      "supports_reasoning_summaries": false,
      "support_verbosity": false,
      "truncation_policy": {{ "mode": "tokens", "limit": 10000 }},
      "supports_image_detail_original": false,
      "supports_search_tool": false,
      "experimental_supported_tools": [],
      "additional_speed_tiers": [],
      "base_instructions": "",
      "web_search_tool_type": "text"
    }}
  ]
}}
"""

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

        env: dict[str, str] = {
            "CODEX_HOME": remote_codex_home,
            # Fail closed: do not let Codex silently use the built-in OpenAI provider.
            "OPENAI_API_KEY": "",
        }

        await self.exec_as_agent(
            environment,
            command=(
                f'mkdir -p "$CODEX_HOME" {shlex.quote(remote_secrets_dir)} '
                f"{shlex.quote(EnvironmentPaths.agent_dir.as_posix())}\n"
                f"cat >\"$CODEX_HOME/config.toml\" <<'TOML'\n"
                f"{self._config_toml(model)}"
                "TOML\n"
                f"cat >\"$CODEX_HOME/model-catalog-shim.json\" <<'JSON'\n"
                f"{self._model_catalog_json(model)}"
                "JSON\n"
                "codex features list | grep '^unified_exec' || true\n"
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
                        f"mkdir -p {EnvironmentPaths.agent_dir.as_posix()}\n"
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


# Backward-compatible import path for older local job configs.
CodexShimAgent = ShimmedCodex
