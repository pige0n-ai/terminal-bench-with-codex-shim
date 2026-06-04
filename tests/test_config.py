from pathlib import Path

import pytest
import yaml

from tb2_codex_shim_bench.config import load_matrix, validate_matrix
from tb2_codex_shim_bench.shim import build_runtime, render_shim_config


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
    assert rendered["models"]["catalog"][0]["apply_patch_tool_type"] == "freeform"
    assert rendered["server"]["base_path"] == "/v1"
    assert rendered["provider"]["profile_config"]["capabilities"] == {
        "supports_reasoning_effort": True,
        "supports_json_schema": False,
    }
    assert rendered["state"] == {"backend": "memory"}


def test_load_matrix_reads_sqlite_state_dir(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["state_backend"] = "sqlite"
    data["defaults"]["state_sqlite_dir"] = "runs/custom-shim-state"

    matrix = load_matrix(write_matrix(tmp_path, data))

    assert matrix.defaults.state_backend == "sqlite"
    assert matrix.defaults.state_sqlite_dir == tmp_path / "runs" / "custom-shim-state"


def test_load_matrix_defaults_sqlite_state_dir(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["state_backend"] = "sqlite"

    matrix = load_matrix(write_matrix(tmp_path, data))

    assert matrix.defaults.state_sqlite_dir == tmp_path / "runs" / "shim-state"


def test_render_sqlite_state_config_requires_path(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["state_backend"] = "sqlite"
    matrix = load_matrix(write_matrix(tmp_path, data))

    with pytest.raises(ValueError, match="sqlite state backend requires a sqlite_path"):
        render_shim_config(matrix.defaults, matrix.models[0])


def test_load_matrix_rejects_invalid_docker_network_prefix(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["docker_network_pool_cidr"] = "10.240.0.0/24"
    data["defaults"]["docker_network_subnet_prefix"] = 16

    with pytest.raises(ValueError, match="docker_network_subnet_prefix"):
        load_matrix(write_matrix(tmp_path, data))


def test_build_runtime_writes_sqlite_path_per_run_and_model(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["state_backend"] = "sqlite"
    data["defaults"]["state_sqlite_dir"] = "runs/shim-state"
    matrix = load_matrix(write_matrix(tmp_path, data))

    runtime = build_runtime(matrix.defaults, matrix.models[0], tmp_path / "runs" / "run-a")
    rendered = yaml.safe_load(runtime.config_path.read_text())

    expected_path = tmp_path / "runs" / "shim-state" / "run-a" / "deepseek_v4_pro.sqlite"
    assert rendered["state"] == {"backend": "sqlite", "sqlite_path": str(expected_path)}


def test_empty_reasoning_levels_render_as_empty_catalog_field(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["reasoning_levels"] = []
    matrix = load_matrix(write_matrix(tmp_path, data))

    rendered = render_shim_config(matrix.defaults, matrix.models[0])

    assert matrix.models[0].reasoning_levels == []
    assert rendered["models"]["catalog"][0]["reasoning_levels"] == []


def test_model_temperature_renders_sampling_config(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["temperature"] = 0
    matrix = load_matrix(write_matrix(tmp_path, data))

    rendered = render_shim_config(matrix.defaults, matrix.models[0])

    assert matrix.models[0].temperature == 0.0
    assert rendered["sampling"] == {"temperature": 0.0}


def test_model_temperature_rejects_out_of_range(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["temperature"] = 2.1

    with pytest.raises(ValueError, match="models\\[0\\]\\.temperature must be between 0 and 2"):
        load_matrix(write_matrix(tmp_path, data))


def test_upstream_retry_settings_render_into_shim_config(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["upstream_max_retries"] = 3
    data["defaults"]["upstream_stream_max_retries"] = 4
    matrix = load_matrix(write_matrix(tmp_path, data))

    rendered = render_shim_config(matrix.defaults, matrix.models[0])

    assert rendered["upstream"]["max_retries"] == 3
    assert rendered["upstream"]["stream_max_retries"] == 4


def test_upstream_retry_settings_reject_out_of_range(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["upstream_stream_max_retries"] = 101

    with pytest.raises(ValueError, match=r"defaults\.upstream_stream_max_retries must be between 0 and 100"):
        load_matrix(write_matrix(tmp_path, data))


def test_apply_patch_tool_type_can_be_disabled_globally(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["apply_patch_tool_type"] = None
    matrix = load_matrix(write_matrix(tmp_path, data))

    rendered = render_shim_config(matrix.defaults, matrix.models[0])

    assert "apply_patch_tool_type" not in rendered["models"]["catalog"][0]


def test_apply_patch_tool_type_rejects_unknown_value(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["apply_patch_tool_type"] = "function"

    with pytest.raises(ValueError, match="defaults\\.apply_patch_tool_type must be 'freeform' or null"):
        load_matrix(write_matrix(tmp_path, data))


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
