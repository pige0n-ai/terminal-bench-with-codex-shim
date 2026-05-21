import json
from pathlib import Path

from tb2_codex_shim_bench.summary import summarize_run


def test_summarize_completed_trial(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    result_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "terminal-bench/example",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-pro"}},
                "agent_result": {
                    "n_input_tokens": 10,
                    "n_cache_tokens": 1,
                    "n_output_tokens": 2,
                    "cost_usd": None,
                },
                "verifier_result": {"rewards": {"reward": 1.0}},
                "exception_info": None,
            }
        )
    )

    summary = summarize_run(tmp_path)

    assert summary["n_trials"] == 1
    assert summary["trials"][0]["status"] == "passed"
    assert summary["models"][0]["n_passed"] == 1


def test_summarize_classifies_catalog_parse_failures(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    agent_dir = result_dir / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "codex.txt").write_text(
        "Error: failed to parse model_catalog_json path `/tmp/codex-home/model-catalog-shim.json` "
        "as JSON: EOF while parsing a value at line 1 column 0"
    )
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "terminal-bench/example",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-pro"}},
                "agent_result": {},
                "verifier_result": {},
                "exception_info": {"exception_type": "NonZeroAgentExitCodeError"},
            }
        )
    )

    summary = summarize_run(tmp_path)

    assert summary["trials"][0]["failure_category"] == "codex_catalog_empty"
    assert summary["models"][0]["failure_categories"] == {"codex_catalog_empty": 1}


def test_summarize_classifies_stream_failures(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    agent_dir = result_dir / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "codex.txt").write_text(
        '{"type":"turn.failed","error":{"message":"stream disconnected before completion: response.failed event received"}}'
    )
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "terminal-bench/example",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-pro"}},
                "agent_result": {},
                "verifier_result": {},
                "exception_info": {"exception_type": "NonZeroAgentExitCodeError"},
            }
        )
    )

    summary = summarize_run(tmp_path)

    assert summary["trials"][0]["failure_category"] == "shim_stream_failed"
    assert summary["models"][0]["failure_categories"] == {"shim_stream_failed": 1}
