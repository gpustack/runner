"""Observer parsing is platform independent; process behavior is tested in test_agent."""

from __future__ import annotations

import json

import pytest

from tools.auto_sync.progress import ProgressObserver, message_tokens


def assistant(content, usage=None, identity="m1"):
    message = {"id": identity, "content": content}
    if usage is not None:
        message["usage"] = usage
    return {"type": "assistant", "message": message}


def frame(*events):
    return "".join(json.dumps(item) + "\n" for item in events).encode()


def observe(stream, **options):
    lines = []
    observer = ProgressObserver(emit=lines.append, **options)
    observer.feed(stream)
    return observer, lines


def test_events_become_concise_single_lines():
    stream = frame(
        {"type": "system", "subtype": "init", "tools": ["secret-list"]},
        assistant([{"type": "text", "text": "Reading the release notes"}]),
        assistant(
            [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "read_file",
                    "input": {"p": "ARGUMENT"},
                },
            ],
            identity="m2",
        ),
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "RESULT-BODY",
                    },
                ],
            },
        },
        assistant(
            [
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "run_shell_command",
                    "input": {},
                },
            ],
            identity="m3",
        ),
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t2",
                        "is_error": True,
                        "content": "BOOM",
                    },
                ],
            },
        },
    )
    _, lines = observe(stream)
    text = "\n".join(lines)
    assert "session started" in text
    assert "assistant: Reading the release notes" in text
    assert "tool started: read_file" in text
    assert "tool completed: read_file" in text
    assert "tool failed: run_shell_command" in text
    assert all(
        line.startswith("auto-sync progress [00:00:00 tokens=") for line in lines
    )
    assert not any(
        word in text for word in ("ARGUMENT", "RESULT-BODY", "BOOM", "secret-list")
    )


def test_thinking_and_final_proposal_are_omitted():
    proposal = json.dumps({"identity": {"pr_number": None}, "groups": []})
    stream = frame(
        assistant([{"type": "thinking", "thinking": "PRIVATE-REASONING"}]),
        assistant([{"type": "text", "text": "PRIVATE-PREFIX " + "x"}], identity="m2"),
        assistant([{"type": "text", "text": proposal}], identity="m3"),
        assistant([{"type": "text", "text": "```json\n" + proposal}], identity="m4"),
        {"type": "result", "subtype": "success", "is_error": False, "result": proposal},
    )
    _, lines = observe(stream)
    text = "\n".join(lines)
    assert "PRIVATE-REASONING" not in text
    assert "groups" not in text
    assert "pr_number" not in text
    assert "session finished" in text


def test_arbitrary_chunk_boundaries_and_utf8():
    stream = frame(
        assistant([{"type": "text", "text": "界" * 3 + " done"}]),
        {"type": "system", "subtype": "init"},
    )
    expected = observe(stream)[1]
    for size in (1, 2, 3, 7):
        lines = []
        observer = ProgressObserver(emit=lines.append)
        for start in range(0, len(stream), size):
            observer.feed(stream[start : start + size])
        assert lines == expected
    assert any("界界界 done" in line for line in expected)


def test_incomplete_line_is_held_until_lf():
    lines = []
    observer = ProgressObserver(emit=lines.append)
    observer.feed(frame({"type": "system", "subtype": "init"})[:-1])
    assert lines == []
    observer.feed(b"\n")
    assert len(lines) == 1


def test_malformed_lines_do_not_break_stream():
    stream = b"not json\n[1,2]\n\xff\xfe\n" + frame(
        {"type": "system", "subtype": "init"},
    )
    _, lines = observe(stream)
    assert len(lines) == 1


@pytest.mark.parametrize("size", [1, 5, 11])
def test_secret_split_across_chunks_never_reaches_output(size):
    secret = "fake-secret-value-123"  # noqa: S105 - fake redaction fixture.
    stream = frame(
        assistant(
            [{"type": "text", "text": f"token {secret} and header {secret[:8]}"}],
        ),
        assistant(
            [{"type": "tool_use", "id": "t", "name": f"use-{secret}", "input": {}}],
            identity="m2",
        ),
    )
    lines = []
    observer = ProgressObserver(emit=lines.append, secrets=[secret])
    for start in range(0, len(stream), size):
        observer.feed(stream[start : start + size])
    text = "\n".join(lines)
    assert secret not in text
    assert "[REDACTED]" in text


def test_json_escaped_secret_is_redacted():
    secret = 'a"b\\c'  # noqa: S105 - fake redaction fixture.
    _, lines = observe(
        frame(assistant([{"type": "text", "text": f"see {secret}"}])),
        secrets=[secret],
    )
    assert secret not in "\n".join(lines)


def test_model_text_cannot_inject_workflow_commands_or_escapes():
    hostile = "hello\n::error::injected\r::add-mask::x\x1b[31m\u2028::set-output name=a::b\x00"
    _, lines = observe(frame(assistant([{"type": "text", "text": hostile}])))
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("auto-sync progress ")
    assert all(ch.isprintable() for ch in line)
    assert "\n" not in line
    assert "\r" not in line
    assert "\x1b" not in line


def test_long_text_is_truncated():
    _, lines = observe(frame(assistant([{"type": "text", "text": "a" * 5000}])))
    assert len(lines[0]) < 300


def test_usage_semantics():
    assert (
        message_tokens({"total_tokens": 10, "input_tokens": 99, "output_tokens": 99})
        == 10
    )
    assert message_tokens({"input_tokens": 7, "output_tokens": 3}) == 10
    # Cache reads are part of the prompt count and are not additive.
    assert (
        message_tokens(
            {"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 5},
        )
        == 10
    )
    for bad in (
        None,
        {},
        {"input_tokens": 0, "output_tokens": 0},
        {"total_tokens": True},
        {"total_tokens": -4},
        {"input_tokens": "9"},
    ):
        assert message_tokens(bad) == 0


def test_duplicates_zero_usage_and_result_do_not_inflate_totals():
    usage = {"input_tokens": 60, "output_tokens": 40}
    stream = frame(
        assistant(
            [{"type": "thinking", "thinking": "t"}],
            {"input_tokens": 0, "output_tokens": 0},
            "z",
        ),
        assistant([{"type": "text", "text": "a"}], usage, "m1"),
        assistant([{"type": "text", "text": "a"}], usage, "m1"),  # re-emitted
        {
            "type": "result",
            "is_error": False,
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
        assistant([{"type": "text", "text": "b"}], {"total_tokens": 25}, "m2"),
    )
    observer, _ = observe(stream, max_tokens=10_000)
    assert observer.tokens == 125
    assert not observer.exceeded


def test_reemitted_message_counts_only_growth():
    stream = frame(
        assistant([{"type": "text", "text": "a"}], {"total_tokens": 10}),
        assistant([{"type": "text", "text": "a"}], {"total_tokens": 30}),
    )
    observer, _ = observe(stream)
    assert observer.tokens == 30


@pytest.mark.parametrize("limit, exceeded", [(101, False), (100, True), (99, True)])
def test_threshold_is_reached_inclusively(limit, exceeded):
    stream = frame(assistant([{"type": "text", "text": "a"}], {"total_tokens": 100}))
    observer, lines = observe(stream, max_tokens=limit)
    assert observer.exceeded is exceeded
    assert observer.stop_requested is exceeded
    assert any("session token budget exceeded" in line for line in lines) is exceeded


def test_no_limit_never_stops():
    observer, _ = observe(
        frame(assistant([{"type": "text", "text": "a"}], {"total_tokens": 10**12})),
    )
    assert not observer.exceeded


def test_heartbeat_reports_elapsed_without_claiming_activity():
    now = [100.0]
    lines = []
    observer = ProgressObserver(emit=lines.append, clock=lambda: now[0], heartbeat=30)
    now[0] = 129.0
    observer.tick()
    assert lines == []
    now[0] = 131.0
    observer.tick()
    assert len(lines) == 1
    assert "00:00:31" in lines[0]
    assert "no new event" in lines[0]
    assert "model" not in lines[0]
    now[0] = 140.0
    observer.tick()
    assert len(lines) == 1  # Next beat only after another quiet period.
    observer.feed(frame({"type": "system", "subtype": "init"}))
    now[0] = 165.0
    observer.tick()
    assert len(lines) == 2


def test_emit_failure_does_not_stop_observation():
    def broken(_line):
        raise BrokenPipeError

    observer = ProgressObserver(emit=broken, max_tokens=5)
    observer.feed(
        frame(assistant([{"type": "text", "text": "a"}], {"total_tokens": 9})),
    )
    assert observer.exceeded
