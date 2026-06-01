# Terminal-Bench Harbor Runners

This repository provides two Harbor runners for Terminal-Bench experiments:

- `tb2-codex-shim-bench`: runs Codex CLI through `codex-shim`.
- `tb2-claude-code-bench`: runs Claude Code against Anthropic-compatible APIs.

Both runners use matrix YAML files to describe datasets, Harbor concurrency,
task filters, and model-specific settings. They write Harbor job directories,
resolved matrix metadata, and summary files under `runs/<run-name>/`.

## Runner Overview

```text
tb2-codex-shim-bench
  -> starts one codex-shim process per matrix model
  -> runs Harbor jobs
  -> installs a pinned Codex CLI in each task container
  -> runs codex exec --json
  -> sends Codex Responses API traffic to codex-shim
  -> codex-shim adapts the request to the configured upstream provider profile
```

```text
tb2-claude-code-bench
  -> runs Harbor jobs
  -> installs a pinned Claude Code CLI in each task container
  -> runs claude
  -> sends Anthropic API traffic to the configured compatible endpoint
```

The Codex runner intentionally does not use Codex `/goal`.

## Requirements

- Docker with Linux containers enabled.
- `harbor` on `PATH`.
- `codex-shim` on `PATH`, or `CODEX_SHIM_BIN` set, for Codex shim runs.
- Provider API keys exported in the host environment, for example
  `DEEPSEEK_API_KEY`.

Install the Python package:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
```

## Codex Shim Runner

Start from the full provider template:

```bash
cp examples/matrix.template.yaml matrix.yaml
```

`examples/matrix.template.yaml` contains commented entries for supported
`codex-shim` provider profiles. Uncomment the models you want to run and keep
ports unique across active entries.

Validate the matrix:

```bash
tb2-codex-shim-bench validate \
  --matrix matrix.yaml \
  --check-env \
  --check-shim-bin
```

Run one task:

```bash
tb2-codex-shim-bench smoke \
  --matrix matrix.yaml \
  --model deepseek_v4_flash \
  --task regex-log \
  --run-name smoke-codex-regex-log
```

Run the configured matrix:

```bash
tb2-codex-shim-bench run --matrix matrix.yaml --run-name codex-matrix
```

Summarize an existing run:

```bash
tb2-codex-shim-bench summarize --run-dir runs/codex-matrix
```

### Codex Matrix Fields

Important `defaults` fields:

- `codex_shim_bin`: path or command used to start `codex-shim`.
- `listen_host`: host interface used by shim processes.
- `docker_host`: hostname used by Harbor task containers to reach the host.
- `harbor_dataset`: Harbor dataset name, for example `terminal-bench@2.0`.
- `harbor_n_attempts`: value passed to Harbor `--n-attempts`.
- `harbor_n_concurrent`: value passed to Harbor `--n-concurrent`.
- `codex_cli_version`: npm version of `@openai/codex` installed in containers.
- `node_version`, `nvm_version`, `root_packages`, `alpine_packages`:
  task-container dependency pins.
- `apply_patch_tool_type`: tool shape advertised to Codex by the model catalog.
- `apply_patch_upstream_tool_type`: tool shape sent upstream by `codex-shim`.
- `state_backend`: shim state backend, usually `sqlite` for long runs.
- `state_sqlite_dir`: directory for per-run, per-model shim SQLite state.
- `tasks`: Harbor task names. Use `[]` to run the full dataset.

Important model fields:

- `id`: local matrix identifier.
- `provider_profile`: `codex-shim` provider profile name.
- `model_slug`: model name used by Codex and the shim catalog.
- `api_key_env`: environment variable containing the upstream API key.
- `port`: host port for this model's shim process.
- `upstream_base_url`: upstream provider base URL.
- `harbor_model_name`: optional `provider/model` label recorded by Harbor.
- `reasoning_enabled`, `reasoning_effort`, `reasoning_levels`: reasoning
  settings exposed through the shim catalog.
- `capabilities`: boolean provider capability overrides only.
- `extra_body`: provider-specific request body fields passed to `codex-shim`.

`capabilities` should not be used to change protocol behavior. Settings such as
endpoint mode, reasoning policy, tool policy, and state policy belong in a
proper `codex-shim` provider profile.

### codex-shim Contract

The generated Codex config and shim config rely on these invariants:

- Codex uses `model_provider = "codex_shim"`.
- The provider uses `wire_api = "responses"`.
- The generated model catalog is referenced with top-level
  `model_catalog_json`.
- `supports_websockets = false` because `codex-shim` serves HTTP and SSE.
- Codex `model`, shim `models.default`, and at least one
  `models.catalog[*].slug` match.
- Upstream auth is read by `codex-shim` from `upstream.api_key_env`; the harness
  never reads or prints secret values.

Supported profiles include:

```text
deepseek-chat, minimax-chat, moonshot-chat, zai-chat, gemini-chat, vertex-chat,
alibaba-chat, alibaba-responses, fireworks-chat, fireworks-responses,
xai-chat, xai-responses, bedrock-chat, bedrock-responses,
openrouter-chat, openrouter-responses, groq-chat, groq-responses,
together-chat, ollama-chat, ollama-responses, llamacpp-chat,
llamacpp-responses, vllm-chat, vllm-responses, sglang-chat, generic-chat
```

## Claude Code Runner

Start from the Claude Code example:

```bash
cp examples/matrix.claude.yaml matrix.claude.yaml
```

The Claude runner does not start `codex-shim`. Each model points Claude Code at
an Anthropic-compatible endpoint through `anthropic_base_url`.

Validate the matrix:

```bash
tb2-claude-code-bench validate --matrix matrix.claude.yaml --check-env
```

Run one task:

```bash
tb2-claude-code-bench smoke \
  --matrix matrix.claude.yaml \
  --model deepseek_v4_flash_nonthinking \
  --task terminal-bench/regex-log \
  --run-name smoke-claude-regex-log
```

Run the configured matrix:

```bash
tb2-claude-code-bench run --matrix matrix.claude.yaml --run-name claude-matrix
```

Summarize an existing run:

```bash
tb2-claude-code-bench summarize --run-dir runs/claude-matrix
```

### Claude Matrix Fields

Important `defaults` fields:

- `harbor_dataset`: Harbor dataset name.
- `harbor_n_attempts`: value passed to Harbor `--n-attempts`.
- `harbor_n_concurrent`: value passed to Harbor `--n-concurrent`.
- `claude_code_version`: npm version of `@anthropic-ai/claude-code`.
- `temperature`, `top_p`, `extra_body`: request body fields exported through
  `CLAUDE_CODE_EXTRA_BODY`.
- `thinking`, `reasoning_effort`, `thinking_display`, `max_thinking_tokens`:
  Claude Code thinking controls.
- `max_output_tokens`: exported as `CLAUDE_CODE_MAX_OUTPUT_TOKENS`.
- `max_turns`, `max_budget_usd`, `fallback_model`: Claude Code agent options.
- `allowed_tools`, `disallowed_tools`: tool allow/block lists passed to Harbor.
- `extra_env`: additional environment variables passed into the task container.
- `tasks`: Harbor task names. Use `[]` to run the full dataset.

Important model fields:

- `id`: local matrix identifier.
- `model_slug`: model name passed to Harbor and Claude Code.
- `api_key_env`: environment variable containing the provider API key.
- `anthropic_base_url`: Anthropic-compatible base URL.
- Any supported default field can be overridden per model.

The runner sets `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`,
`ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`,
`CLAUDE_CODE_SUBAGENT_MODEL`, and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` for each Harbor invocation.

## Tasks And Attempts

`tasks` entries are passed to Harbor as `--include-task-name`. Leave `tasks` as
`[]` to run the whole dataset, or use the `smoke` subcommand to run a single
task without editing the matrix.

`harbor_n_attempts` maps directly to Harbor `--n-attempts`. Use `1` for smoke
runs and higher values for repeated benchmark attempts.

## Docker Networking

Codex shim runs start shim processes on the host. Harbor task containers reach
them at:

```text
http://<docker_host>:<port>/v1
```

The default `docker_host` is `host.docker.internal`. On Linux, Docker must
provide that hostname through host-gateway or equivalent daemon/network
configuration. The Codex runner performs a connectivity check before launching
Harbor.

## Outputs

Both runners write:

- `runs/<run-name>/jobs/`: raw Harbor job directories.
- `runs/<run-name>/matrix.resolved.json`: resolved model metadata and Harbor
  command records.
- `runs/<run-name>/summary.json` and `runs/<run-name>/summary.csv`: result
  rollups.
- `runs/<run-name>/harbor-*.log`: Harbor stdout/stderr for each model/task
  invocation.

Codex shim runs also write:

- `runs/<run-name>/generated/*.yaml`: generated `codex-shim` configs.
- `runs/<run-name>/shim-logs/*.log`: shim logs.
- `runs/<run-name>/jobs/*/*/agent/config.toml`: Codex config copied from the
  task container.
- `runs/<run-name>/jobs/*/*/agent/model-catalog-shim.json`: model catalog used
  by Codex.
- `runs/<run-name>/jobs/*/*/agent/codex-version.txt`: installed Codex CLI
  version.
- `runs/<run-name>/jobs/*/*/agent/codex-features.txt`: enabled Codex feature
  surface.

Harbor uploads are explicit. These runners do not pass `--upload` by default.

## Stopping Runs

Press `Ctrl+C` in the terminal running the benchmark command. If child
processes remain, inspect the process group and terminate it:

```bash
ps -eo pid,ppid,pgid,stat,cmd | grep -E 'tb2-(codex-shim|claude-code)-bench|harbor run|codex-shim|claude'
kill -TERM -<PGID>
```

On exit, both runners inspect only the Harbor job directories started by the
current process. They remove Docker containers and compose networks whose
`com.docker.compose.project` label matches the Harbor trial names under those
job directories. Harbor job names include a per-process invocation suffix, so
two concurrent processes with the same `--run-name` still get separate job
directories. The runners do not run global Docker prune commands, so concurrent
benchmark processes and unrelated services are left alone.

Avoid `docker system prune` while iterating on benchmark runs; it removes cached
task images and slows down subsequent runs.

## Tests

```bash
pytest -q -s
```

Failures are classified rather than hidden. Missing env vars, unreachable shim
processes, Harbor registry errors, upstream API errors, and agent/verifier
failures remain explicit.
