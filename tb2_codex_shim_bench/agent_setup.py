from __future__ import annotations

import shlex


def setup_command(
    *,
    config_toml: str,
    remote_secrets_dir: str,
    agent_dir: str,
    health_url: str,
    models_url: str,
) -> str:
    catalog_file = "$CODEX_HOME/model-catalog-shim.json"
    return (
        "set -euo pipefail\n"
        f'mkdir -p "$CODEX_HOME" {shlex.quote(remote_secrets_dir)} {shlex.quote(agent_dir)}\n'
        "cat >\"$CODEX_HOME/config.toml\" <<'TOML'\n"
        f"{config_toml}"
        "TOML\n"
        "health_ready=0\n"
        "for i in $(seq 1 30); do\n"
        f"  if curl -sS --max-time 2 {shlex.quote(health_url)} | grep -q '\"ok\"'; then\n"
        "    health_ready=1\n"
        "    break\n"
        "  fi\n"
        "  sleep 1\n"
        "done\n"
        "test \"$health_ready\" = 1\n"
        'catalog_tmp="$(mktemp "$CODEX_HOME/model-catalog-shim.json.tmp.XXXXXX")"\n'
        'trap \'rm -f "$catalog_tmp"\' EXIT\n'
        f"curl -fsS --max-time 10 --retry 5 --retry-delay 1 {shlex.quote(models_url)} >\"$catalog_tmp\"\n"
        "test -s \"$catalog_tmp\"\n"
        "node -e 'JSON.parse(require(\"fs\").readFileSync(process.argv[1], \"utf8\"))' \"$catalog_tmp\"\n"
        f"mv \"$catalog_tmp\" \"{catalog_file}\"\n"
        "trap - EXIT\n"
        "codex --version >\"$CODEX_HOME/codex-version.txt\"\n"
        "codex features list >\"$CODEX_HOME/codex-features.txt\" 2>&1\n"
        "grep '^unified_exec' \"$CODEX_HOME/codex-features.txt\"\n"
        f"cp \"$CODEX_HOME/config.toml\" {shlex.quote(agent_dir)}/config.toml\n"
        f"cp \"{catalog_file}\" {shlex.quote(agent_dir)}/model-catalog-shim.json\n"
        f"cp \"$CODEX_HOME/codex-version.txt\" {shlex.quote(agent_dir)}/codex-version.txt\n"
        f"cp \"$CODEX_HOME/codex-features.txt\" {shlex.quote(agent_dir)}/codex-features.txt\n"
    )
