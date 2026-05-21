from __future__ import annotations

import shlex


def setup_command(
    *,
    config_toml: str,
    remote_secrets_dir: str,
    agent_dir: str,
    model_catalog_json: str,
) -> str:
    catalog_file = "$CODEX_HOME/model-catalog-shim.json"
    return (
        "set -euo pipefail\n"
        f'mkdir -p "$CODEX_HOME" {shlex.quote(remote_secrets_dir)} {shlex.quote(agent_dir)}\n'
        # Harbor runs this command in a fresh non-interactive shell. On glibc
        # images, Codex and Node are installed through nvm during agent install,
        # so setup must load nvm again before validating the catalog or probing
        # Codex features.
        'if [ -s "$HOME/.nvm/nvm.sh" ]; then . "$HOME/.nvm/nvm.sh"; fi\n'
        "cat >\"$CODEX_HOME/config.toml\" <<'TOML'\n"
        f"{config_toml}"
        "TOML\n"
        'catalog_tmp="$(mktemp "$CODEX_HOME/model-catalog-shim.json.tmp.XXXXXX")"\n'
        'trap \'rm -f "$catalog_tmp"\' EXIT\n'
        "cat >\"$catalog_tmp\" <<'JSON'\n"
        f"{model_catalog_json}\n"
        "JSON\n"
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
