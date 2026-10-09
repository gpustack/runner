"""Actions summaries show outcomes without dumping transport data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.auto_sync.summary import result_markdown, tools_markdown


def test_session_failure_is_shown_once_with_candidate_versions():
    reason = (
        "agent process failed or timed out (exit 53): Warning: running headless\n"
        "FatalTurnLimitedError: Reached max session turns for this session."
    )
    result = {
        "stage": "research",
        "status": "failed",
        "reason": reason,
        "durations": {"research_seconds": 1094.204},
        "candidates": [
            {"subscription": "cuda/vllm", "status": "failed", "reason": reason},
            {"subscription": "cann/vllm", "status": "failed", "reason": reason},
        ],
    }
    context = {
        "discovery": [
            {"subscription": "cuda/vllm", "engine_version": "0.31.0"},
            {
                "subscription": "cann/vllm",
                "engine_version": "0.27.1",
                "plugin_version": "0.27.1rc1",
            },
        ],
    }
    markdown = result_markdown(result, context)
    assert "**FAILED**" in markdown
    assert markdown.count("session turn limit") == 1
    assert "18m 14s" in markdown
    assert "| cuda/vllm | 0.31.0 |" in markdown
    assert "| cann/vllm | 0.27.1 | 0.27.1rc1 |" in markdown
    assert "Warning:" not in markdown
    assert "schema_version" not in markdown


def test_untrusted_candidate_reason_cannot_inject_markdown():
    result = {
        "stage": "validate",
        "status": "ready",
        "reason": "Candidate validation completed.",
        "candidates": [
            {
                "subscription": "cuda/vllm",
                "status": "blocked",
                "reason": "![image](https://example.invalid)\n| <details> **claim**",
            },
        ],
    }
    markdown = result_markdown(result, {})
    assert "![image]" not in markdown
    assert "<details>" not in markdown
    assert "**claim**" not in markdown
    assert "\\|" in markdown


def test_wall_time_failure_is_visible_after_startup_warning():
    reason = (
        "agent process failed or timed out (exit 55): "
        + "Warning: running headless. " * 20
        + "Run aborted: wall-clock budget of 2400s exceeded (--max-wall-time)."
    )
    markdown = result_markdown(
        {"stage": "research", "status": "failed", "reason": reason},
        {},
    )
    assert "wall-clock budget" in markdown
    assert "exit 55" in markdown
    assert "Warning:" not in markdown


def test_publication_links_to_actual_pull_request():
    markdown = result_markdown(
        {
            "stage": "publish",
            "status": "created",
            "reason": "Published.",
            "pr_number": 42,
        },
        {"identity": {"repository": "gpustack/runner"}},
    )
    assert "https://github.com/gpustack/runner/pull/42" in markdown
    assert "[#42]" in markdown


def test_tool_summary_omits_install_paths_and_cache_key():
    markdown = tools_markdown(
        {
            "cache_hit": True,
            "duration_seconds": 2.497,
            "bin": "private-tool-location",
            "cache_key": "private-cache-identity",
        },
    )
    assert "Hit" in markdown
    assert "2.5s" in markdown
    assert "private-tool-location" not in markdown
    assert "private-cache-identity" not in markdown
