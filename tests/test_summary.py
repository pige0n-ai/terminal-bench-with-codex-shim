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
