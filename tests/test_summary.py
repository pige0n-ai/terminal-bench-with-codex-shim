import json
import sqlite3
from pathlib import Path

import yaml

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
                "agent_execution": {"started_at": "2026-06-04T00:00:00Z", "finished_at": "2026-06-04T00:00:03Z"},
                "verifier": {"started_at": "2026-06-04T00:00:03Z", "finished_at": "2026-06-04T00:00:05Z"},
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


def test_summarize_reads_nested_harbor_timing(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    result_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "terminal-bench/example",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-pro"}},
                "agent_result": {},
                "verifier_result": {"rewards": {"reward": 1.0}},
                "agent_execution": {"started_at": "2026-06-04T00:00:00Z", "finished_at": "2026-06-04T00:00:03.500000Z"},
                "verifier": {"started_at": "2026-06-04T00:00:04Z", "finished_at": "2026-06-04T00:00:06Z"},
                "exception_info": None,
            }
        )
    )

    trial = summarize_run(tmp_path)["trials"][0]

    assert trial["agent_time_sec"] == 3.5
    assert trial["verifier_time_sec"] == 2.0


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


def test_summarize_reads_codex_shim_sqlite_metrics(tmp_path: Path):
    run_dir = tmp_path / "run-a"
    result_dir = run_dir / "jobs" / "job-a" / "trial-a"
    agent_dir = result_dir / "agent"
    generated_dir = run_dir / "generated"
    agent_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    sqlite_path = tmp_path / "shim.sqlite"
    (agent_dir / "codex.txt").write_text('{"type":"turn.completed"}\n')
    (generated_dir / "deepseek.yaml").write_text(yaml.safe_dump({"state": {"sqlite_path": str(sqlite_path)}}))
    connection = sqlite3.connect(sqlite_path)
    connection.execute("create table responses (response_json text, created_at integer)")
    connection.executemany(
        "insert into responses values (?, ?)",
        [
            (
                json.dumps(
                    {
                        "usage": {
                            "input_tokens": 100,
                            "input_tokens_details": {"cached_tokens": 80},
                            "output_tokens": 10,
                            "output_tokens_details": {"reasoning_tokens": 3},
                            "total_tokens": 110,
                        },
                        "output": [{"type": "function_call"}, {"type": "reasoning"}],
                    }
                ),
                1,
            ),
            (
                json.dumps(
                    {
                        "usage": {
                            "input_tokens": 90,
                            "input_tokens_details": {"cached_tokens": 70},
                            "output_tokens": 5,
                            "output_tokens_details": {"reasoning_tokens": 2},
                            "total_tokens": 95,
                        },
                        "output": [{"type": "function_call"}],
                    }
                ),
                2,
            ),
        ],
    )
    connection.commit()
    connection.close()
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "terminal-bench/example",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-flash"}},
                "agent_result": {"n_input_tokens": 190, "n_cache_tokens": 150, "n_output_tokens": 15},
                "verifier_result": {"rewards": {"reward": 1.0}},
                "exception_info": None,
            }
        )
    )

    trial = summarize_run(run_dir)["trials"][0]

    assert trial["n_requests"] == 2
    assert trial["n_turns"] == 2
    assert trial["n_tool_calls"] == 2
    assert trial["n_cache_read_tokens"] == 150
    assert trial["n_reasoning_tokens"] == 5
    assert trial["n_input_tokens"] == 190


def test_summarize_reads_claude_code_stream_metrics(tmp_path: Path):
    result_dir = tmp_path / "jobs" / "job-a" / "trial-a"
    agent_dir = result_dir / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "claude-code.txt").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "id": "msg-a",
                            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100, "output_tokens": 0},
                            "content": [{"type": "tool_use", "id": "tool-a", "name": "Bash"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "id": "msg-a",
                            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100, "output_tokens": 0},
                            "content": [{"type": "tool_use", "id": "tool-a", "name": "Bash"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "id": "msg-b",
                            "usage": {"input_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 200, "output_tokens": 0},
                            "content": [{"type": "tool_use", "id": "tool-b", "name": "Read"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "usage": {
                            "input_tokens": 15,
                            "cache_creation_input_tokens": 7,
                            "cache_read_input_tokens": 300,
                            "output_tokens": 11,
                        },
                    }
                ),
            ]
        )
    )
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_name": "terminal-bench/example",
                "trial_name": "trial-a",
                "agent_info": {"model_info": {"name": "deepseek-v4-flash"}},
                "agent_result": {"n_input_tokens": 315, "n_cache_tokens": 307, "n_output_tokens": 11, "cost_usd": 0.5},
                "verifier_result": {"rewards": {"reward": 1.0}},
                "exception_info": None,
            }
        )
    )

    trial = summarize_run(tmp_path)["trials"][0]

    assert trial["n_requests"] == 2
    assert trial["n_turns"] == 2
    assert trial["n_tool_calls"] == 2
    assert trial["n_cache_creation_tokens"] == 7
    assert trial["n_cache_read_tokens"] == 300
    assert trial["n_cache_tokens"] == 307
    assert trial["n_reasoning_tokens"] is None
