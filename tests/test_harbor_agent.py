import os
import subprocess
from pathlib import Path

from tb2_codex_shim_bench.agent_setup import setup_command


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def fake_bin_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env python3
import os, sys
url = sys.argv[-1]
if url.endswith('/healthz'):
    print('{"status":"ok"}')
elif url.endswith('/models'):
    sys.stdout.write(os.environ.get('FAKE_MODELS_BODY', '{"models":[{"slug":"deepseek-v4-flash"}]}'))
else:
    print(f'unexpected url: {url}', file=sys.stderr)
    sys.exit(22)
""",
    )
    write_executable(
        bin_dir / "node",
        """#!/usr/bin/env python3
import json, sys
with open(sys.argv[-1]) as handle:
    json.load(handle)
""",
    )
    write_executable(
        bin_dir / "codex",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli 0.131.0'
elif [ "${1:-}" = "features" ] && [ "${2:-}" = "list" ]; then
  echo 'unified_exec stable'
else
  echo "unexpected codex args: $*" >&2
  exit 2
fi
""",
    )
    return bin_dir


def run_setup(tmp_path: Path, *, models_body: str | None = None) -> subprocess.CompletedProcess[str]:
    code_home = tmp_path / "codex-home"
    agent_dir = tmp_path / "agent"
    bin_dir = fake_bin_dir(tmp_path)
    command = setup_command(
        config_toml='model = "deepseek-v4-flash"\n',
        remote_secrets_dir=str(tmp_path / "secrets"),
        agent_dir=str(agent_dir),
        health_url="http://127.0.0.1:8878/healthz",
        models_url="http://127.0.0.1:8878/v1/models",
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(code_home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if models_body is not None:
        env["FAKE_MODELS_BODY"] = models_body
    return subprocess.run(
        ["bash", "-lc", command],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_setup_command_atomically_writes_valid_catalog_and_artifacts(tmp_path: Path):
    result = run_setup(tmp_path)

    assert result.returncode == 0, result.stderr
    agent_dir = tmp_path / "agent"
    assert (agent_dir / "config.toml").read_text() == 'model = "deepseek-v4-flash"\n'
    assert (agent_dir / "model-catalog-shim.json").read_text() == '{"models":[{"slug":"deepseek-v4-flash"}]}'
    assert (agent_dir / "codex-version.txt").read_text() == "codex-cli 0.131.0\n"
    assert (agent_dir / "codex-features.txt").read_text() == "unified_exec stable\n"
    assert not list((tmp_path / "codex-home").glob("model-catalog-shim.json.tmp.*"))


def test_setup_command_rejects_empty_catalog_without_clobbering_previous_catalog(tmp_path: Path):
    code_home = tmp_path / "codex-home"
    code_home.mkdir()
    catalog = code_home / "model-catalog-shim.json"
    catalog.write_text('{"models":[{"slug":"old"}]}')

    result = run_setup(tmp_path, models_body="")

    assert result.returncode != 0
    assert catalog.read_text() == '{"models":[{"slug":"old"}]}'
    assert not list(code_home.glob("model-catalog-shim.json.tmp.*"))
    assert not (tmp_path / "agent" / "model-catalog-shim.json").exists()


def test_setup_command_rejects_invalid_catalog_without_clobbering_previous_catalog(tmp_path: Path):
    code_home = tmp_path / "codex-home"
    code_home.mkdir()
    catalog = code_home / "model-catalog-shim.json"
    catalog.write_text('{"models":[{"slug":"old"}]}')

    result = run_setup(tmp_path, models_body="not-json")

    assert result.returncode != 0
    assert catalog.read_text() == '{"models":[{"slug":"old"}]}'
    assert not list(code_home.glob("model-catalog-shim.json.tmp.*"))
    assert not (tmp_path / "agent" / "model-catalog-shim.json").exists()
