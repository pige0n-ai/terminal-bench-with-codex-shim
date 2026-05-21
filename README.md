# Terminal-Bench 2.0 via Codex CLI and codex-shim

This repository runs Terminal-Bench 2.0 model/provider matrices through Codex CLI while routing all model traffic through `codex-shim`.

`codex-shim` presents a Codex-compatible `/v1/responses` API. Codex must always be configured with `wire_api = "responses"`; the shim then adapts requests to upstream Chat Completions or native Responses providers according to the configured provider profile.

## Architecture

```text
tb2-codex-shim-bench
  -> starts one codex-shim process per model/provider entry
  -> runs Harbor jobs
  -> Harbor Docker task container
  -> ShimmedCodex writes container-local CODEX_HOME
  -> codex exec --json
  -> codex-shim /v1/responses
  -> upstream provider
```

The harness intentionally does not use Codex `/goal`.

## codex-shim contract

The harness depends on these `codex-shim` rules:

- Codex side uses `model_provider = "codex_shim"`, top-level `model_catalog_json`, and provider `wire_api = "responses"`.
- `supports_websockets = false` is required because `codex-shim` serves HTTP + SSE.
- Codex `model`, shim `models.default`, and at least one `models.catalog[*].slug` must match.
- Shim upstream auth is controlled by the shim YAML `upstream.api_key_env`; the harness never reads or prints secret values.
- Chat-backed profiles are adapted internally. Their tool-call and streaming behavior can vary by provider, so results must be interpreted with the provider profile attached.
- Matrix `capabilities` supports only boolean provider capability overrides, such as `supports_json_schema` or `supports_reasoning_effort`. It intentionally does not expose `endpoint_mode`, `reasoning_policy`, `tool_policy`, or `state_policy`; those change protocol/state semantics and should be encoded in a proper `codex-shim` profile instead.

Known provider profiles include:

```text
deepseek-chat, minimax-chat, moonshot-chat, zai-chat, gemini-chat, vertex-chat,
alibaba-chat, alibaba-responses, fireworks-chat, fireworks-responses,
xai-chat, xai-responses, bedrock-chat, bedrock-responses,
openrouter-chat, openrouter-responses, groq-chat, groq-responses,
together-chat, ollama-chat, ollama-responses, llamacpp-chat,
llamacpp-responses, vllm-chat, vllm-responses, sglang-chat, generic-chat
```

## Quick start

Prerequisites:

- Docker with Linux containers enabled.
- `harbor` on `PATH`.
- `codex-shim` built or installed locally.
- Provider API keys exported in the host environment, for example `DEEPSEEK_API_KEY`.

Install the Python project:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
```

Prepare a matrix:

```bash
cp examples/matrix.template.yaml matrix.yaml
```

`examples/matrix.template.yaml` includes every supported provider profile.
Model entries are commented out by default; uncomment at least one entry before
validating or running. `matrix.yaml` is ignored by git so local model
selections, paths, and ports do not get committed accidentally.

The key `defaults` fields are:

```yaml
defaults:
  codex_shim_bin: ${CODEX_SHIM_BIN:-codex-shim}
  listen_host: 0.0.0.0
  docker_host: host.docker.internal
  harbor_bin: harbor
  harbor_dataset: terminal-bench@2.0
  harbor_jobs_dir: runs
  harbor_n_attempts: 1
  harbor_n_concurrent: 1
  codex_cli_version: 0.131.0
  node_version: "22"
  nvm_version: 0.40.2
  root_packages: [curl, ripgrep]
  alpine_packages: [curl, bash, nodejs, npm, ripgrep]
  apply_patch_tool_type: freeform
  apply_patch_upstream_tool_type: structured
  upstream_max_retries: 2
  upstream_stream_max_retries: 2
  reasoning_enabled: true
  reasoning_effort: xhigh
  context_window: 1000000
  state_backend: sqlite
  state_sqlite_dir: runs/shim-state
  logging_level: info
  tasks:
    - regex-log
```

For Terminal-Bench 2.0, keep `harbor_dataset: terminal-bench@2.0`. Task filters
are dataset-local names such as `regex-log`; the harness passes them to Harbor
as `--include-task-name`. Use `tasks: []` to run the full dataset.

`harbor_n_attempts` maps to Harbor `--n-attempts`. For leaderboard-style runs,
set it to `5`; for smoke tests, keep it at `1`.

Dependency-sensitive runs should pin `codex_cli_version`, `node_version`,
`nvm_version`, and package lists. The default `codex_cli_version: 0.131.0`
matches the latest version observed in run-7; without this pin Harbor's Codex
agent installs `@openai/codex@latest` inside each task container, which can drift
within a single run. `apply_patch_tool_type: freeform` is emitted into the shim
model catalog so Codex exposes `apply_patch` as a callable tool instead of only
mentioning patching in instructions.

For long Terminal-Bench runs, prefer `state_backend: sqlite`. The harness writes one
SQLite database per run/model under `state_sqlite_dir/<run-name>/<model-id>.sqlite`,
which avoids keeping shim state only in process memory.

Per-model entries may override safe provider/model-level fields:

```yaml
models:
  - id: deepseek_v4_flash
    provider_profile: deepseek-chat
    model_slug: deepseek-v4-flash
    api_key_env: DEEPSEEK_API_KEY
    port: 8877
    upstream_base_url: https://api.deepseek.com
    context_window: 1000000
    reasoning_enabled: true
    reasoning_effort: xhigh
    reasoning_levels: [xhigh, high]
    harbor_model_name: deepseek/deepseek-v4-flash
    capabilities:
      supports_reasoning_effort: true
      supports_json_schema: false
    extra_body:
      thinking: enabled
```

`harbor_model_name` is optional. When set to `provider/model`, Harbor records
the provider in `agent_info.model_info.provider`; the Codex CLI config still
uses the final path segment as the shim model slug.

Validate:

```bash
tb2-codex-shim-bench validate --matrix matrix.yaml --check-env --check-shim-bin
```

Run one smoke task:

```bash
tb2-codex-shim-bench smoke \
  --matrix matrix.yaml \
  --model deepseek_v4_flash \
  --task regex-log \
  --run-name smoke-regex-log
```

Run the configured matrix:

```bash
tb2-codex-shim-bench run --matrix matrix.yaml --run-name tb2-matrix
```

Summarize an existing run:

```bash
tb2-codex-shim-bench summarize --run-dir runs/tb2-matrix
```

Run tests:

```bash
pytest -q -s
```

## Docker networking

Each shim listens on `0.0.0.0:<port>` on the host. Harbor task containers call it as:

```text
http://host.docker.internal:<port>/v1
```

On Linux, Docker must support `host.docker.internal` via host gateway or equivalent daemon/network configuration. The harness includes a Docker connectivity check before running Harbor.

## Running And Stopping

Full Terminal-Bench 2.0 with `harbor_n_attempts: 5` runs `89 * 5 = 445`
trials per model. The first run can spend substantial time pulling task images
and installing Codex CLI inside task containers. Harbor `--n-concurrent` means
concurrent scheduled trials, not necessarily the exact number of visible
`docker ps` containers at every moment.

To stop a run, press `Ctrl+C` in the terminal running `tb2-codex-shim-bench`.
If processes remain, inspect and stop the process group:

```bash
ps -eo pid,ppid,pgid,stat,cmd | rg 'tb2-codex-shim-bench|harbor run|codex-shim'
kill -TERM -<PGID>
```

Avoid `docker system prune` during active development; it removes cached task
images and makes future runs slower.

## Outputs

Each run writes:

- `runs/<run-name>/generated/*.yaml`: generated `codex-shim` configs.
- `runs/<run-name>/jobs/*/*/agent/config.toml`: exact Codex config used inside a task container.
- `runs/<run-name>/jobs/*/*/agent/model-catalog-shim.json`: exact model catalog consumed by Codex.
- `runs/<run-name>/jobs/*/*/agent/codex-version.txt` and `codex-features.txt`: pinned Codex CLI version and enabled feature surface.
- `runs/<run-name>/shim-logs/*.log`: one shim log per model.
- `runs/<run-name>/jobs/`: raw Harbor job directories.
- `runs/<run-name>/matrix.resolved.json`: resolved model and command metadata.
- `runs/<run-name>/summary.json` and `summary.csv`: result rollup.

Harbor uploads are explicit. This harness does not pass `--upload` by default.
If you upload a job later with `harbor upload`, the agent name recorded in new
trial results is `ShimmedCodex`.

Failures are classified rather than hidden. Missing env vars, unreachable shim processes, Harbor registry errors, upstream API errors, and agent/verifier failures remain explicit.
