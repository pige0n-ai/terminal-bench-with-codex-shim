import importlib
import json
import os
import subprocess
import sys
import types
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
        model_catalog_json=(models_body if models_body is not None else '{"models":[{"slug":"deepseek-v4-flash"}]}'),
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(code_home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
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
    assert (agent_dir / "model-catalog-shim.json").read_text() == '{"models":[{"slug":"deepseek-v4-flash"}]}\n'
    assert (agent_dir / "codex-version.txt").read_text() == "codex-cli 0.131.0\n"
    assert (agent_dir / "codex-features.txt").read_text() == "unified_exec stable\n"
    assert not list((tmp_path / "codex-home").glob("model-catalog-shim.json.tmp.*"))



def test_setup_command_loads_nvm_for_node_and_codex(tmp_path: Path):
    code_home = tmp_path / "codex-home"
    agent_dir = tmp_path / "agent"
    bin_dir = fake_bin_dir(tmp_path)
    nvm_bin = tmp_path / "nvm-bin"
    nvm_bin.mkdir()
    (nvm_bin / "node").write_text((bin_dir / "node").read_text())
    (nvm_bin / "codex").write_text((bin_dir / "codex").read_text())
    (nvm_bin / "node").chmod(0o755)
    (nvm_bin / "codex").chmod(0o755)

    nvm_dir = tmp_path / ".nvm"
    nvm_dir.mkdir()
    (nvm_dir / "nvm.sh").write_text(f'export PATH="{nvm_bin}:$PATH"\n')

    command = setup_command(
        config_toml='model = "deepseek-v4-flash"\n',
        remote_secrets_dir=str(tmp_path / "secrets"),
        agent_dir=str(agent_dir),
        model_catalog_json='{"models":[{"slug":"deepseek-v4-flash"}]}',
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(code_home)
    env["HOME"] = str(tmp_path)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    (bin_dir / "node").unlink()
    (bin_dir / "codex").unlink()

    result = subprocess.run(
        ["bash", "-lc", command],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (agent_dir / "codex-version.txt").read_text() == "codex-cli 0.131.0\n"

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


def import_shimmed_codex(monkeypatch):
    base_module = types.ModuleType("harbor.agents.installed.base")
    codex_module = types.ModuleType("harbor.agents.installed.codex")
    environment_module = types.ModuleType("harbor.environments.base")
    context_module = types.ModuleType("harbor.models.agent.context")
    paths_module = types.ModuleType("harbor.models.trial.paths")

    def with_prompt_template(func):
        return func

    class Codex:
        _REMOTE_CODEX_HOME = Path("/tmp/codex-home")
        _REMOTE_CODEX_SECRETS_DIR = Path("/tmp/codex-secrets")
        _OUTPUT_FILENAME = "codex.txt"

        def __init__(self, *args, **kwargs):
            pass

    class BaseEnvironment:
        pass

    class AgentContext:
        pass

    class EnvironmentPaths:
        agent_dir = Path("/tmp/agent")

    base_module.with_prompt_template = with_prompt_template
    codex_module.Codex = Codex
    environment_module.BaseEnvironment = BaseEnvironment
    context_module.AgentContext = AgentContext
    paths_module.EnvironmentPaths = EnvironmentPaths

    for module_name in [
        "harbor",
        "harbor.agents",
        "harbor.agents.installed",
        "harbor.environments",
        "harbor.models",
        "harbor.models.agent",
        "harbor.models.trial",
    ]:
        monkeypatch.setitem(sys.modules, module_name, types.ModuleType(module_name))
    monkeypatch.setitem(sys.modules, "harbor.agents.installed.base", base_module)
    monkeypatch.setitem(sys.modules, "harbor.agents.installed.codex", codex_module)
    monkeypatch.setitem(sys.modules, "harbor.environments.base", environment_module)
    monkeypatch.setitem(sys.modules, "harbor.models.agent.context", context_module)
    monkeypatch.setitem(sys.modules, "harbor.models.trial.paths", paths_module)
    sys.modules.pop("tb2_codex_shim_bench.harbor_agent", None)
    return importlib.import_module("tb2_codex_shim_bench.harbor_agent").ShimmedCodex


def test_shimmed_codex_accepts_dict_catalog_json(tmp_path, monkeypatch):
    """ShimmedCodex serializes a dict model_catalog_json back to JSON."""
    ShimmedCodex = import_shimmed_codex(monkeypatch)

    catalog_dict = {"models": [{"slug": "deepseek-v4-flash"}]}
    expected_json = json.dumps(catalog_dict)

    agent = ShimmedCodex(
        logs_dir=tmp_path / "logs",
        model_name="deepseek-v4-flash",
        codex_shim_base_url="http://127.0.0.1:8877/v1",
        model_catalog_json=catalog_dict,
    )

    actual = json.loads(agent.model_catalog_json)
    assert actual == catalog_dict
    assert agent.model_catalog_json == expected_json


def test_shimmed_codex_accepts_list_catalog_json(tmp_path, monkeypatch):
    """ShimmedCodex wraps a list model_catalog_json in {models: [...]} and serializes."""
    ShimmedCodex = import_shimmed_codex(monkeypatch)

    catalog_list = [{"slug": "deepseek-v4-flash"}]
    expected_dict = {"models": catalog_list}

    agent = ShimmedCodex(
        logs_dir=tmp_path / "logs",
        model_name="deepseek-v4-flash",
        codex_shim_base_url="http://127.0.0.1:8877/v1",
        model_catalog_json=catalog_list,
    )

    actual = json.loads(agent.model_catalog_json)
    assert actual == expected_dict


def test_shimmed_codex_passes_through_string_catalog_json(tmp_path, monkeypatch):
    """ShimmedCodex passes through a JSON string model_catalog_json unchanged."""
    ShimmedCodex = import_shimmed_codex(monkeypatch)

    catalog_str = '''{"models": [{"slug": "deepseek-v4-flash"}]}'''

    agent = ShimmedCodex(
        logs_dir=tmp_path / "logs",
        model_name="deepseek-v4-flash",
        codex_shim_base_url="http://127.0.0.1:8877/v1",
        model_catalog_json=catalog_str,
    )

    assert agent.model_catalog_json == catalog_str
