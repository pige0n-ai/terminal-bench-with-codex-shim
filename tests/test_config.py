from pathlib import Path

import pytest
import yaml

from tb2_codex_shim_bench.config import load_matrix, validate_matrix
from tb2_codex_shim_bench.shim import render_shim_config


def write_matrix(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def base_matrix() -> dict:
    return {
        "defaults": {
            "codex_shim_bin": "/bin/echo",
            "tasks": ["regex-log"],
        },
        "models": [
            {
                "id": "deepseek_v4_pro",
                "provider_profile": "deepseek-chat",
                "model_slug": "deepseek-v4-pro",
                "api_key_env": "DEEPSEEK_API_KEY",
                "port": 8877,
                "reasoning_levels": ["xhigh", "high"],
                "capabilities": {
                    "supports_reasoning_effort": True,
                    "supports_json_schema": False,
                },
            }
        ],
    }


def test_load_matrix_and_render_shim_config(tmp_path: Path):
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    model = matrix.models[0]
    rendered = render_shim_config(matrix.defaults, model)

    assert rendered["provider"]["profile_config"]["profile"] == "deepseek-chat"
    assert rendered["upstream"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert rendered["models"]["default"] == "deepseek-v4-pro"
    assert rendered["models"]["catalog"][0]["slug"] == "deepseek-v4-pro"
    assert rendered["server"]["base_path"] == "/v1"
    assert rendered["provider"]["profile_config"]["capabilities"] == {
        "supports_reasoning_effort": True,
        "supports_json_schema": False,
    }


def test_duplicate_ports_are_rejected(tmp_path: Path):
    data = base_matrix()
    data["models"].append({**data["models"][0], "id": "other"})
    matrix_path = write_matrix(tmp_path, data)

    with pytest.raises(ValueError, match="duplicate port"):
        load_matrix(matrix_path)


def test_unknown_provider_is_rejected(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["provider_profile"] = "not-real"

    with pytest.raises(ValueError, match="unknown provider_profile"):
        load_matrix(write_matrix(tmp_path, data))


def test_check_env_rejects_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        validate_matrix(matrix, check_files=False, check_env=True)


def test_rejects_non_boolean_capability(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["capabilities"] = {"supports_json_schema": "false"}

    with pytest.raises(ValueError, match="must be a boolean"):
        load_matrix(write_matrix(tmp_path, data))


def test_rejects_enum_capability_override(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["capabilities"] = {"endpoint_mode": "native_responses"}

    with pytest.raises(ValueError, match="not a supported boolean capability"):
        load_matrix(write_matrix(tmp_path, data))
