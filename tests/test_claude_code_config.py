from pathlib import Path

import pytest
import yaml

from tb2_claude_code_bench.config import load_matrix, validate_matrix


def write_matrix(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "matrix.claude.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def base_matrix() -> dict:
    return {
        "defaults": {
            "harbor_dataset": "terminal-bench/terminal-bench-2-1",
            "harbor_jobs_dir": "runs",
            "harbor_n_attempts": 5,
            "harbor_n_concurrent": 6,
            "claude_code_version": "2.1.144",
            "temperature": 0,
            "thinking_display": "omitted",
            "disallowed_tools": "WebSearch,WebFetch",
            "tasks": ["regex-log"],
        },
        "models": [
            {
                "id": "deepseek_v4_flash_nonthinking",
                "model_slug": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "anthropic_base_url": "https://api.deepseek.com/anthropic",
                "thinking": "disabled",
                "reasoning_effort": "high",
            }
        ],
    }


def test_load_matrix_resolves_defaults_and_sampling(tmp_path: Path):
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))
    model = matrix.models[0]

    assert matrix.defaults.harbor_jobs_dir == tmp_path / "runs"
    assert matrix.defaults.temperature == 0.0
    assert matrix.defaults.disallowed_tools == "WebSearch,WebFetch"
    assert model.resolved_extra_body(matrix.defaults) == {"temperature": 0.0}
    assert model.resolved_extra_env(matrix.defaults) == {"CLAUDE_CODE_EXTRA_BODY": '{"temperature":0.0}'}


def test_model_overrides_sampling_and_merges_extra_body(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["extra_body"] = {"metadata": {"user_id": "tb21"}, "temperature": 1.0}
    data["models"][0]["temperature"] = 0
    data["models"][0]["top_p"] = 0.5
    data["models"][0]["extra_body"] = {"service_tier": "auto"}
    matrix = load_matrix(write_matrix(tmp_path, data))

    assert matrix.models[0].resolved_extra_body(matrix.defaults) == {
        "metadata": {"user_id": "tb21"},
        "service_tier": "auto",
        "temperature": 0.0,
        "top_p": 0.5,
    }


def test_rejects_out_of_range_temperature(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["temperature"] = 2.1

    with pytest.raises(ValueError, match=r"models\[0\]\.temperature must be between 0 and 2"):
        load_matrix(write_matrix(tmp_path, data))


def test_rejects_out_of_range_top_p(tmp_path: Path):
    data = base_matrix()
    data["defaults"]["top_p"] = 1.1

    with pytest.raises(ValueError, match=r"defaults\.top_p must be between 0 and 1"):
        load_matrix(write_matrix(tmp_path, data))


def test_rejects_unknown_thinking_mode(tmp_path: Path):
    data = base_matrix()
    data["models"][0]["thinking"] = "sometimes"

    with pytest.raises(ValueError, match=r"models\[0\]\.thinking must be one of"):
        load_matrix(write_matrix(tmp_path, data))


def test_check_env_rejects_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    matrix = load_matrix(write_matrix(tmp_path, base_matrix()))

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        validate_matrix(matrix, check_env=True)
