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
                    "n_cache_read_tokens": 3,
                    "n_cache_creation_tokens": 4,
                    "n_cache_tokens": 1,
                    "n_output_tokens": 2,
                    "n_reasoning_tokens": 5,
                    "n_requests": 6,
                    "n_turns": 7,
                    "n_tool_calls": 8,
                    "agent_time_sec": 9.5,
                    "cost_usd": None,
                },
                "verifier_result": {"rewards": {"reward": 1.0}, "duration_sec": 1.25},
                "duration_sec": 12.5,
                "exception_info": None,
            }
        )
    )

    summary = summarize_run(tmp_path)

    assert summary["n_trials"] == 1
    assert summary["trials"][0]["status"] == "passed"
    assert summary["trials"][0]["n_total_tokens"] == 12
    assert summary["trials"][0]["wall_time_sec"] == 12.5
    assert summary["trials"][0]["agent_time_sec"] == 9.5
    assert summary["trials"][0]["verifier_time_sec"] == 1.25
    assert summary["models"][0]["n_passed"] == 1
    assert summary["models"][0]["n_requests"] == 6
    assert summary["models"][0]["n_turns"] == 7
    assert summary["models"][0]["n_tool_calls"] == 8
    assert summary["models"][0]["n_cache_read_tokens"] == 3
    assert summary["models"][0]["n_cache_creation_tokens"] == 4
    assert summary["models"][0]["n_reasoning_tokens"] == 5
    assert summary["models"][0]["metric_counts"]["n_requests"] == 1


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


def test_summarize_does_not_fail_on_bad_result_json(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    result_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text("{not json")

    summary = summarize_run(tmp_path)

    assert summary["n_trials"] == 1
    assert summary["trials"][0]["status"] == "errored"
    assert summary["trials"][0]["exception_type"] == "summary_read_error:JSONDecodeError"
