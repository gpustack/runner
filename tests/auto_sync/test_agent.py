# ruff: noqa: E402, PLR2004
# Imports follow the repository root setup; numeric bounds are fixture expectations.
"""Exercise the pinned CLI against local protocols, never a paid endpoint."""

import base64
import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "model"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(FIXTURES))
from server import endpoint

from tools.auto_sync import agent, proposal
from tools.auto_sync.agent import ProcessResult, run_agent, run_process, tool_guard
from tools.auto_sync.model import ConfigurationError, normalize_inputs
from tools.auto_sync.progress import ProgressObserver
from tools.auto_sync.proposal import parse_agent_output, stream_lines


@pytest.fixture
def tool_bin(tmp_path, monkeypatch):
    if sys.platform == "darwin":
        # Only controlled local CLI fixtures use this boundary. It cannot prove
        # Linux orphan cleanup and is not an available production fallback.
        monkeypatch.setattr(agent, "_process_runner", lambda: _local_cli_process)
    value = os.environ.get("AUTO_SYNC_TOOL_BIN")
    assert value, (
        "Required pinned CLI unavailable: run bootstrap.sh, set AUTO_SYNC_TOOL_BIN to its bin output"
    )
    path = Path(value)
    for binary, version in [("node", "v24.14.0"), ("qwen", "0.25.0")]:
        result = subprocess.run(  # noqa: S603 - fixed pinned-tool version check.
            [str(path / binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env={"HOME": str(tmp_path), "PATH": str(path) + os.pathsep + os.defpath},
        )
        assert result.returncode == 0
        assert version == result.stdout.strip()
    return path


def _local_cli_process(
    argv,
    *,
    cwd,
    env,
    deadline,
    stop_file,
    input_text,
    observer=None,  # noqa: ARG001 - the local fixture has no live tail.
):
    with tempfile.TemporaryFile() as input_stream:
        input_stream.write(input_text.encode("utf-8"))
        input_stream.seek(0)
        process = subprocess.Popen(  # noqa: S603 - controlled fixture CLI only.
            argv,
            cwd=cwd,
            env=env,
            stdin=input_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    expires = time.monotonic() + deadline
    timed_out = False
    collected = False
    try:
        while True:
            remaining = expires - time.monotonic()
            if remaining <= 0 or (stop_file and stop_file.exists()):
                timed_out = remaining <= 0
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=2)
                collected = True
                break
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                collected = True
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        # A collected group may be recycled; signal only still-running processes.
        if not collected:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    return ProcessResult(process.returncode, stdout, stderr, timed_out)


def test_local_cli_process_does_not_signal_reaped_group(monkeypatch, tmp_path):
    calls = []

    def detect(pid, sig):
        calls.append((pid, sig))
        msg = "reaped process group must not be signalled"
        raise PermissionError(msg)

    monkeypatch.setattr(os, "killpg", detect)
    result = _local_cli_process(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        env={},
        deadline=10,
        stop_file=None,
        input_text="",
    )
    assert result.returncode == 0
    assert not result.timed_out
    assert result.stdout.strip() == "ok"
    assert calls == []


def test_unsupported_platform_rejects_before_launch_and_probe(
    monkeypatch,
    tmp_path,
    workspace,
):
    monkeypatch.setattr(sys, "platform", "unsupported")
    with pytest.raises(ConfigurationError, match="Linux"):
        run_process(
            [sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            env={},
            deadline=1,
        )
    with endpoint("openai", tools=False) as (url, requests):
        with pytest.raises(ConfigurationError, match="Linux"):
            run_agent(
                config(url, "openai", **{"llm-auth-token": "fake-first,fake-second"}),
                workspace=workspace,
                tool_bin=tmp_path,
                prompt="Fixture",
                runtime_dir=tmp_path / "runtime",
            )
        assert requests == []
        assert not (tmp_path / "runtime").exists()


@pytest.fixture
def workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(FIXTURES / "AGENTS.md", project)
    skills = project / ".agents" / "skills"
    skills.mkdir(parents=True)
    shutil.copytree(FIXTURES / "fixture-release", skills / "fixture-release")
    (project / ".claude").mkdir()
    (project / ".claude" / "skills").symlink_to("../.agents/skills")
    return project


def config(url, protocol, **extra):
    return normalize_inputs(
        {
            "llm-url": url + "/v1",
            "llm-model": "fixture-model",
            "llm-auth-token": "fake-contract-token",
            "llm-protocol": protocol,
            "llm-auth-header": "X-Fixture-Token",
            "llm-extra-headers": "X-Fixture=yes",
            "llm-timeout": "2",
            **extra,
        },
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Requires the Linux supervisor")
def test_stdin_eof_and_secret_redaction(tmp_path):
    result = run_process(
        [
            sys.executable,
            "-c",
            "import sys; assert sys.stdin.read() == ''; print('fake-secret')",
        ],
        cwd=tmp_path,
        env={},
        deadline=2,
        secrets=["fake-secret"],
    )
    assert result.returncode == 0
    assert not result.timed_out
    assert result.stdout.strip() == "[REDACTED]"


def test_real_cli_receives_large_prompt_without_argv_limit(
    tool_bin,
    workspace,
    tmp_path,
):
    prompt = (
        "START_OF_RELEASE_CONTEXT\n"
        + "x" * (2 * 1024 * 1024)
        + "\nEND_OF_RELEASE_CONTEXT"
    )
    with endpoint("openai", tools=False) as (url, requests):
        result = run_agent(
            config(url, "openai", **{"llm-context-window-size": "1000000"}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt=prompt,
            runtime_dir=tmp_path / "runtime",
            deadline=30,
        )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not result.timed_out
    body = requests[-1]["body"]
    user = [message for message in body["messages"] if message["role"] == "user"]
    contents = [message["content"] for message in user]
    text = "\n".join(
        content
        if isinstance(content, str)
        else "\n".join(block["text"] for block in content if block["type"] == "text")
        for content in contents
    )
    assert prompt in text


def test_real_cli_uses_outer_deadline_without_wall_time_budget(
    tool_bin,
    workspace,
    tmp_path,
    monkeypatch,
):
    runner = agent._process_runner()  # noqa: SLF001 - controlled fixture boundary.
    observed = {}

    def capture_budget(argv, *, cwd, env, deadline, stop_file, input_text, observer):
        observed["argv"] = argv
        observed["deadline"] = deadline
        observed["settings"] = json.loads(
            (Path(env["QWEN_HOME"]) / "settings.json").read_text(),
        )
        return runner(
            argv,
            cwd=cwd,
            env=env,
            deadline=10,
            stop_file=stop_file,
            input_text=input_text,
            observer=observer,
        )

    monkeypatch.setattr(agent, "_process_runner", lambda: capture_budget)
    with endpoint("openai", tools=False) as (url, requests):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Return the fixture result.",
            runtime_dir=tmp_path / "runtime",
        )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not result.timed_out
    assert len(requests) == 1
    assert "--max-wall-time" not in observed["argv"]
    assert "maxWallTimeSeconds" not in observed["settings"]["model"]
    assert observed["deadline"] == 3300


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_real_cli_assembles_proposal_files(
    tool_bin,
    workspace,
    tmp_path,
    protocol,
):
    original = json.loads(
        (ROOT / "tests/auto_sync/fixtures/proposals/ready.json").read_text(),
    )
    draft = json.loads(json.dumps(original))
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(draft["groups"][0].pop("patch").encode())
    draft["groups"][0]["patch_file"] = patch.name
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft))
    output = tmp_path / "proposal.json"
    command = {
        "command": "cd "
        + shlex.quote(str(ROOT))
        + " && "
        + shlex.join(
            [
                sys.executable,
                "-m",
                "tools.auto_sync.assemble",
                "--draft",
                str(draft_path),
                "--output",
                str(output),
            ],
        ),
        "description": "Assemble the fixture proposal from patch files",
        "timeout": 5000,
    }
    with endpoint(protocol, calls=[("run_shell_command", command)]) as (url, requests):
        result = run_agent(
            config(url, protocol),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Assemble the supplied proposal draft.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not result.timed_out
    assert len(requests) == 2
    assert json.loads(output.read_text()) == original


def test_prompt_over_cli_stdin_limit_rejects_before_token_probe(
    tool_bin,
    workspace,
    tmp_path,
):
    with (
        endpoint("openai", tools=False) as (url, requests),
        pytest.raises(ConfigurationError, match="prompt exceeds"),
    ):
        run_agent(
            config(url, "openai", **{"llm-auth-token": "fake-first,fake-second"}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="界" * (3 * 1024 * 1024),
            runtime_dir=tmp_path / "runtime",
        )
    assert requests == []
    assert not (tmp_path / "runtime").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Requires the Linux supervisor")
def test_deadline_kills_child_process_group(tmp_path):
    marker = tmp_path / "escaped"
    child = "import time,pathlib; time.sleep(1); pathlib.Path('escaped').touch(); time.sleep(30)"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    start = time.monotonic()
    result = run_process(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        env={},
        deadline=0.2,
    )
    assert result.timed_out
    assert time.monotonic() - start < 2
    time.sleep(1)
    assert not marker.exists()


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_real_cli_protocol_turns_instructions_skill_mcp(
    tool_bin,
    workspace,
    tmp_path,
    protocol,
):
    extra = '{"temperature":0.2,"top_p":0.7}'
    if protocol != "anthropic":
        extra = '{"temperature":0.2,"top_p":0.7,"reasoning_effort":"high"}'
    with endpoint(protocol) as (url, requests):
        result = run_agent(
            config(
                url,
                protocol,
                **{"llm-temperature": "0.9", "llm-extra-body": extra},
            ),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Read fixture-release and the MCP evidence, then return the assessment.",
            runtime_dir=tmp_path / "runtime",
            mcp_servers={
                "fixture": {
                    "command": sys.executable,
                    "args": [str(FIXTURES / "mcp.py")],
                    "trust": True,
                },
            },
            deadline=30,
        )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not result.timed_out
    count = len(requests)
    assert count == 3, result.stderr + result.stdout
    assert "INSTRUCTION_EVIDENCE_LOADED" in json.dumps(requests[0]["body"])
    assert "SKILL_EVIDENCE_LOADED" in json.dumps(requests[1]["body"])
    assert "MCP_EVIDENCE_LOADED" in json.dumps(requests[2]["body"])
    for request in requests:
        body = request["body"]
        assert body["model"] == "fixture-model"
        assert body["temperature"] == 0.2
        assert body["top_p"] == 0.7
        headers = {key.lower(): value for key, value in request["headers"].items()}
        assert headers["x-fixture-token"] == "fake-contract-token"
        assert headers["x-fixture"] == "yes"
        assert (
            request["path"]
            == {
                "openai": "/v1/chat/completions",
                "openai-responses": "/v1/responses",
                "anthropic": "/v1/messages",
            }[protocol]
        )
        names = {
            tool.get("name", tool.get("function", {}).get("name"))
            for tool in body["tools"]
        }
        assert not names.intersection(
            {
                "ask_user_question",
                "enter_plan_mode",
                "exit_plan_mode",
                "agent",
                "create_sub_session",
                "workflow",
                "team_create",
            },
        )
        if protocol == "openai":
            assert body["reasoning_effort"] == "high"
            assert body["thinking"] == {"type": "disabled", "clear_thinking": True}
        elif protocol == "openai-responses":
            assert body["reasoning"]["effort"] == "high"
            assert "thinking" not in body
            assert "reasoning_effort" not in body
        else:
            assert "thinking" not in body
            assert "reasoning_effort" not in body
    assert "fake-contract-token" not in result.stdout + result.stderr


def test_deepwiki_mcp_carries_no_collected_secret(
    tool_bin,
    workspace,
    tmp_path,
    monkeypatch,
):
    servers = {
        **agent.github_mcp(tool_bin, "fake-github-token"),
        **agent.deepwiki_mcp(),
    }
    # The documented hosted endpoint needs no authentication material.
    assert servers["deepwiki"] == {"httpUrl": "https://mcp.deepwiki.com/mcp"}
    assert servers["github"]["env"] == {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "fake-github-token",
    }
    captured = {}
    real_observer = agent.ProgressObserver

    def spy(**kwargs):
        captured["secrets"] = list(kwargs["secrets"])
        return real_observer(**kwargs)

    monkeypatch.setattr(agent, "ProgressObserver", spy)
    with endpoint("openai", tools=False) as (url, _requests):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Fixture",
            runtime_dir=tmp_path / "runtime",
            mcp_servers=servers,
            deadline=10,
        )
    assert result.returncode == 0, result.stderr + result.stdout
    # Only model and GitHub MCP credentials are collected; DeepWiki adds none.
    assert set(captured["secrets"]) == {
        "fake-contract-token",
        "yes",
        "fake-github-token",
    }


def test_rejects_candidate_configuration_before_request(tool_bin, workspace, tmp_path):
    (workspace / ".env").write_text("OPENAI_API_KEY=untrusted\n")
    with endpoint("openai") as (url, requests):
        with pytest.raises(ConfigurationError, match="configuration"):
            run_agent(
                config(url, "openai"),
                workspace=workspace,
                tool_bin=tool_bin,
                prompt="Fixture",
                runtime_dir=tmp_path / "runtime",
            )
        assert not requests


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_real_cli_request_timeout_is_seconds(tool_bin, workspace, tmp_path, protocol):
    with endpoint(protocol, delay=1, tools=False) as (url, requests):
        result = run_agent(
            config(url, protocol, **{"llm-timeout": "0.1"}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Fixture timeout",
            runtime_dir=tmp_path / "runtime",
            deadline=6,
        )
    assert requests
    assert result.returncode != 0
    assert 0.05 <= requests[0]["closed_after"] < 0.5
    errors = [
        event.get("error", {}).get("message", "")
        for line in stream_lines(result.stdout)
        if line.strip()
        for event in [json.loads(line)]
        if event.get("type") == "result" and event.get("is_error") is True
    ]
    error_text = (result.stderr + " ".join(errors)).lower()
    assert result.timed_out or "timeout" in error_text or "timed out" in error_text


@pytest.mark.skipif(sys.platform != "linux", reason="Requires the Linux supervisor")
def test_deadline_kills_detached_child(tmp_path):
    child = "import time,pathlib; time.sleep(1); pathlib.Path('escaped').touch(); time.sleep(3)"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}], start_new_session=True); time.sleep(10)"
    result = run_process(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        env={},
        deadline=0.2,
    )
    assert result.timed_out
    time.sleep(1)
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("mode", ["success", "timeout", "stop"])
@pytest.mark.parametrize("inherit_streams", [False, True])
@pytest.mark.skipif(sys.platform != "linux", reason="Requires the Linux supervisor")
def test_fast_orphan_cannot_write_after_return(tmp_path, mode, inherit_streams):
    child = (
        "import os,time,pathlib;pathlib.Path('started').write_text(str(os.getpid()));time.sleep(0.8);"
        "pathlib.Path('escaped').touch()"
    )
    streams = (
        ""
        if inherit_streams
        else ",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL"
    )
    launcher = (
        "import subprocess,sys;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}],"
        f"start_new_session=True,stdin=subprocess.DEVNULL{streams})"
    )
    parent = (
        "import subprocess,sys,time,pathlib;time.sleep(0.03);"
        f"subprocess.run([sys.executable,'-c',{launcher!r}],check=True)\n"
        "for _ in range(100):\n"
        " if pathlib.Path('started').exists(): break\n"
        " time.sleep(0.001)\n"
        + ("pathlib.Path('stop').touch();" if mode == "stop" else "")
        + ("time.sleep(2)" if mode != "success" else "")
    )
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        env={},
        deadline=0.3 if mode == "timeout" else 1,
        stop_file=tmp_path / "stop",
    )
    assert time.monotonic() - started < 2
    assert result.timed_out == (mode == "timeout")
    assert result.returncode == (0 if mode == "success" else -9)
    pid = int((tmp_path / "started").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    time.sleep(0.9)
    assert not (tmp_path / "escaped").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Requires the Linux supervisor")
def test_supervisor_failure_does_not_wait_for_inherited_streams(tmp_path):
    child = (
        "import os,signal,time;os.setsid();os.kill(os.getppid(),signal.SIGKILL);"
        "time.sleep(0.8)"
    )
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", child],
        cwd=tmp_path,
        env={},
        deadline=0.2,
    )
    assert time.monotonic() - started < 0.7
    assert result.returncode != 0
    assert "cleanup could not be confirmed" in result.stderr
    time.sleep(0.8)  # The finite failure fixture has no surviving work after this test.


def test_command_guard_rejects_background_and_long_commands(tmp_path):
    state = tmp_path / "guard.json"
    accepted = {
        "hook_event_name": "PreToolUse",
        "tool_name": "run_shell_command",
        "tool_input": {
            "command": "printf ready",
            "is_background": False,
            "timeout": 100,
        },
    }
    assert (
        tool_guard(accepted, state)["hookSpecificOutput"]["permissionDecision"]
        == "allow"
    )
    for parameters in ({"timeout": 300001}, {"is_background": True}):
        rejected = {**accepted, "tool_input": {**accepted["tool_input"], **parameters}}
        assert (
            tool_guard(rejected, state)["hookSpecificOutput"]["permissionDecision"]
            == "deny"
        )


def test_guard_stops_after_two_unchanged_retries(tmp_path):
    state = tmp_path / "guard.json"
    failure = {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "run_shell_command",
        "tool_input": {"command": "false"},
        "error": "failed",
    }
    assert tool_guard(failure, state) == {}
    assert tool_guard(failure, state) == {}
    assert tool_guard(failure, state)["continue"] is False


def test_real_cli_shell_stdin_is_eof(tool_bin, workspace, tmp_path):
    command = {
        "command": 'python3 -c \'import sys; print("SHELL_EOF_" + str(sys.stdin.read() == ""))\'',
        "description": "Check stdin EOF",
        "is_background": False,
        "timeout": 1000,
    }
    with endpoint("openai", calls=[("run_shell_command", command)]) as (url, requests):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Check stdin.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == 2
    assert "SHELL_EOF_True" in json.dumps(requests[1]["body"])


def test_real_cli_guard_rejects_command_over_limit(tool_bin, workspace, tmp_path):
    command = {
        "command": "touch guard-failed",
        "description": "Rejected fixture",
        "is_background": False,
        "timeout": 300001,
    }
    with endpoint("openai", calls=[("run_shell_command", command)]) as (url, requests):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Exercise command guard.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == 2
    assert "300 seconds" in json.dumps(requests[1]["body"])
    assert not (workspace / "guard-failed").exists()


def test_real_cli_stops_unchanged_tool_failure(tool_bin, workspace, tmp_path):
    command = {
        "command": "printf x >> attempts; false",
        "description": "Repeat failing fixture",
        "is_background": False,
        "timeout": 1000,
    }
    with endpoint("openai", calls=[("run_shell_command", command)] * 5) as (
        url,
        _requests,
    ):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Exercise retry guard.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode != 0
    assert len((workspace / "attempts").read_text()) == 3
    assert "retries exhausted" in result.stderr


@pytest.mark.parametrize("limits", [{"max_tool_calls": 1}, {"max_turns": 1}])
def test_real_cli_session_budgets(tool_bin, workspace, tmp_path, limits):
    with endpoint("openai") as (url, requests):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Exercise budgets.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
            **limits,
        )
    assert result.returncode != 0
    count = len(requests)
    assert count <= 2
    assert not result.timed_out


def test_turn_limit_preserves_completed_tool_events(tool_bin, workspace, tmp_path):
    with endpoint(
        "openai",
        calls=[("run_shell_command", {"command": "printf 'fake-contract-token'"})],
    ) as (url, requests):
        result = run_agent(
            config(url, "openai"),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Exercise the tool, then return the assessment.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
            max_turns=1,
        )
    assert result.returncode == 53
    assert len(requests) == 1
    assert not result.timed_out
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    blocks = [
        block
        for event in events
        for block in event.get("message", {}).get("content", [])
        if isinstance(block, dict)
    ]
    call = next(block for block in blocks if block.get("type") == "tool_use")
    response = next(block for block in blocks if block.get("type") == "tool_result")
    assert call["name"] == "run_shell_command"
    assert response["tool_use_id"] == call["id"]
    assert "fake-contract-token" not in result.stdout + result.stderr
    assert "[REDACTED]" in json.dumps(response)


def _streamed(stdout, returncode=0, stderr=""):
    """Pretend the pinned process already produced this captured stdout."""

    def runner(*_args, **_kwargs):
        return ProcessResult(returncode, stdout, stderr)

    return lambda: runner


@pytest.mark.parametrize("header", ["null", "false", "true", "42", 'quoted"value'])
def test_header_redaction_preserves_nested_proposal_scalars(header, monkeypatch):
    # A header value that is also a JSON scalar word must not rewrite the nested
    # proposal; an actual echo of the value is still scrubbed as text.
    proposal = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    events = [
        {"type": "assistant", "message": {"content": f"echo {header} here"}},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps(proposal),
        },
    ]
    stdout = "".join(json.dumps(item) + "\n" for item in events)
    monkeypatch.setattr(agent, "_process_runner", _streamed(stdout))
    result = run_process(["qwen"], cwd=Path.cwd(), env={}, deadline=1, secrets=[header])
    parsed = parse_agent_output(result)
    assert parsed == proposal
    assert parsed["identity"]["pr_number"] is None
    assert parsed["groups"][0]["rows"][0]["torch"] is None
    echoed = json.loads(stream_lines(result.stdout)[0])
    assert echoed["message"]["content"] == "echo [REDACTED] here"


@pytest.mark.parametrize(
    "secret, scalar",
    [("null", None), ("false", False), ("true", True), ("0", 0)],
)
def test_every_json_scalar_word_survives_nested_redaction(secret, scalar):
    document = {"value": scalar, "list": [scalar], "echo": f"literal {secret}"}
    event = {"type": "result", "result": json.dumps(document)}
    scrubbed = proposal.redact(event, proposal.ordered_secrets([secret]))
    nested = json.loads(scrubbed["result"])
    assert nested == {"value": scalar, "list": [scalar], "echo": "literal [REDACTED]"}


def test_process_redaction_keeps_literal_unicode_inside_one_event(monkeypatch):
    event = {"type": "assistant", "text": "a\u2028b\u2029c\u0085d"}
    stdout = json.dumps(event, ensure_ascii=False) + "\n"
    monkeypatch.setattr(agent, "_process_runner", _streamed(stdout))
    result = run_process(
        ["qwen"],
        cwd=Path.cwd(),
        env={},
        deadline=1,
        secrets=["never"],
    )
    assert json.loads(result.stdout) == event


def test_secret_header_redaction_preserves_json_booleans(tool_bin, workspace, tmp_path):
    with endpoint(
        "openai",
        calls=[("run_shell_command", {"command": "printf false"})],
    ) as (url, requests):
        result = run_agent(
            config(url, "openai", **{"llm-extra-headers": "X-Fixture=false"}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Read the evidence, then return the assessment.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == 2
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["is_error"] is False
    assert "[REDACTED]" in result.stdout


@pytest.mark.parametrize(
    "protocol,body,expected",
    [
        ("openai", {"top_k": 17}, {"top_k": 17}),
        ("openai-responses", {"top_k": 17}, {"top_k": 17}),
        ("openai-responses", {"store": False}, {"store": False}),
        (
            "openai-responses",
            {"include": ["reasoning.encrypted_content"], "reasoning_effort": "high"},
            {"include": ["reasoning.encrypted_content"]},
        ),
        (
            "openai",
            {"thinking": {"type": "enabled", "clear_thinking": True}, "temperature": 0},
            {"thinking": {"type": "enabled", "clear_thinking": True}, "temperature": 0},
        ),
        (
            "openai-responses",
            {"reasoning_effort": "max", "max_output_tokens": 2048},
            {
                "reasoning": {"effort": "max", "summary": "auto"},
                "max_output_tokens": 2048,
            },
        ),
        (
            "anthropic",
            {
                "thinking": {"type": "enabled", "budget_tokens": 1024},
                "max_tokens": 2048,
            },
            {
                "thinking": {"type": "enabled", "budget_tokens": 1024},
                "max_tokens": 2048,
            },
        ),
    ],
)
def test_real_cli_explicit_native_fields(
    tool_bin,
    workspace,
    tmp_path,
    protocol,
    body,
    expected,
):
    with endpoint(protocol, tools=False) as (url, requests):
        result = run_agent(
            config(url, protocol, **{"llm-extra-body": json.dumps(body)}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Check native fields.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    count = len(requests)
    assert count == 1
    for key, value in expected.items():
        assert requests[0]["body"][key] == value


@pytest.mark.parametrize("clear,expected", [("", True), ("false", False)])
def test_real_cli_glm_history_clear_reaches_api(
    tool_bin,
    workspace,
    tmp_path,
    clear,
    expected,
):
    with endpoint("openai", tools=False) as (url, requests):
        result = run_agent(
            config(
                url,
                "openai",
                **{
                    "llm-model": "GLM-5.3-Flash",
                    "llm-thinking-clear": clear,
                    "llm-extra-body": '{"enable_thinking":true,"reasoning_effort":"max"}',
                },
            ),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Check configured history clearing.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == 1
    assert requests[0]["body"]["thinking"] == {
        "type": "enabled",
        "clear_thinking": expected,
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_real_cli_explicit_thinking_sampling_and_effort(
    tool_bin,
    workspace,
    tmp_path,
    enabled,
):
    extra = {
        "enable_thinking": enabled,
        "reasoning_effort": "max",
        "temperature": 1,
        "top_p": 0.9,
    }
    with endpoint("openai", tools=False) as (url, requests):
        result = run_agent(
            config(
                url,
                "openai",
                **{
                    "llm-temperature": "0.2",
                    "llm-top-p": "0.1",
                    "llm-reasoning-effort": "low",
                    "llm-extra-body": json.dumps(extra),
                },
            ),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Check explicit provider controls.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == 1
    body = requests[0]["body"]
    assert all(body[key] == value for key, value in extra.items())
    assert "thinking" not in body


@pytest.mark.parametrize("enabled", [True, False])
def test_real_cli_image_capability_controls_request_content(
    tool_bin,
    workspace,
    tmp_path,
    enabled,
):
    image = workspace / "fixture.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
        ),
    )
    with endpoint("openai", calls=[("read_file", {"file_path": str(image)})]) as (
        url,
        requests,
    ):
        result = run_agent(
            config(url, "openai", **{"llm-modalities": json.dumps({"image": enabled})}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Read the fixture image.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == 2
    parts = [
        part
        for message in requests[1]["body"]["messages"]
        if isinstance(message.get("content"), list)
        for part in message["content"]
    ]
    images = [part for part in parts if part["type"] == "image_url"]
    if enabled:
        assert len(images) == 1
        assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")
    else:
        assert images == []
        assert "does not support" in json.dumps(requests[1]["body"])
    assert all("modalities" not in request["body"] for request in requests)


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_real_cli_stop_hook_reports_effective_context_window(
    tool_bin,
    workspace,
    tmp_path,
    monkeypatch,
    protocol,
):
    observed = tmp_path / "context.json"
    runner = agent._process_runner()  # noqa: SLF001 - controlled fixture boundary.

    def capture_context(argv, *, cwd, env, deadline, stop_file, input_text, observer):
        settings_path = Path(env["QWEN_HOME"]) / "settings.json"
        settings = json.loads(settings_path.read_text())
        settings["hooks"]["Stop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": shlex.join(
                            [
                                sys.executable,
                                str(FIXTURES / "context_hook.py"),
                                str(observed),
                            ],
                        ),
                        "timeout": 5000,
                    },
                ],
            },
        ]
        settings_path.write_text(json.dumps(settings))
        return runner(
            argv,
            cwd=cwd,
            env=env,
            deadline=deadline,
            stop_file=stop_file,
            input_text=input_text,
            observer=observer,
        )

    monkeypatch.setattr(agent, "_process_runner", lambda: capture_context)
    with endpoint(protocol, tools=False) as (url, requests):
        result = run_agent(
            config(url, protocol, **{"llm-context-window-size": "1000000"}),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Check effective context window.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    event = json.loads(observed.read_text())
    assert event["hook_event_name"] == "Stop"
    assert event["context_limit"] == 1000000
    assert event["input_tokens"] > 0
    assert len(requests) == 1
    assert "contextWindowSize" not in requests[0]["body"]


@pytest.mark.parametrize(
    "body",
    [
        {"store": True},
        {"include": ["message.output_text.logprobs"], "reasoning_effort": "high"},
        {"prompt_cache_key": "explicit-fixture-key"},
    ],
)
def test_responses_rejects_overridden_fields_without_requests(
    tool_bin,
    workspace,
    tmp_path,
    body,
):
    with endpoint("openai-responses", tools=False) as (url, requests):
        with pytest.raises(ConfigurationError):
            run_agent(
                config(url, "openai-responses", **{"llm-extra-body": json.dumps(body)}),
                workspace=workspace,
                tool_bin=tool_bin,
                prompt="Check rejection.",
                runtime_dir=tmp_path / "runtime",
                deadline=5,
            )
        assert requests == []


@pytest.mark.parametrize(
    "protocol,path",
    [
        ("openai", "/gateway/chat/completions"),
        ("openai-responses", "/gateway/v1/responses"),
        ("anthropic", "/gateway/v1/messages"),
    ],
)
@pytest.mark.parametrize("tokens", ["fake-first", "fake-first,fake-second"])
def test_real_cli_and_probe_share_non_root_endpoint(
    tool_bin,
    workspace,
    tmp_path,
    protocol,
    path,
    tokens,
):
    with endpoint(protocol, tools=False, path=path) as (url, requests):
        result = run_agent(
            config(
                url,
                protocol,
                **{
                    "llm-url": url + "/gateway",
                    "llm-auth-token": tokens,
                },
            ),
            workspace=workspace,
            tool_bin=tool_bin,
            prompt="Check prefix.",
            runtime_dir=tmp_path / "runtime",
            deadline=10,
        )
    assert result.returncode == 0, result.stderr
    assert len(requests) == (2 if "," in tokens else 1)
    assert all(request["path"] == path for request in requests)
    for request in requests:
        headers = {key.lower(): value for key, value in request["headers"].items()}
        assert headers["x-fixture-token"] == "fake-first"
        assert headers["x-fixture"] == "yes"


LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Required Linux test: live tail and descendant cleanup use the supervisor",
)
BUDGET_EVENT = json.dumps(
    {
        "type": "assistant",
        "message": {
            "id": "m1",
            "content": [{"type": "text", "text": "working"}],
            "usage": {"input_tokens": 60, "output_tokens": 40},
        },
    },
)
# A detached descendant that would write after the supervisor returned.
ESCAPING_CHILD = (
    "import subprocess,sys;subprocess.Popen([sys.executable,'-c',"
    "\"import time,pathlib;time.sleep(1);pathlib.Path('escaped').touch()\"],"
    "start_new_session=True,stdin=subprocess.DEVNULL,"
    "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
)


def _budget_child(*, linger=30):
    return (
        f"import sys,time;exec({ESCAPING_CHILD!r});"
        f"print({BUDGET_EVENT!r},flush=True);time.sleep({linger})"
    )


@LINUX_ONLY
def test_large_stdin_still_honors_the_deadline(tmp_path, monkeypatch):
    # A supervisor that stalls before reading stdin must not outlive the deadline.
    root = Path(agent.__file__).resolve().parents[2]
    package = tmp_path / "tools" / "auto_sync"
    package.mkdir(parents=True)
    for module in (root / "tools" / "auto_sync").glob("*.py"):
        (package / module.name).write_text(module.read_text())
    supervisor = package / "agent.py"
    supervisor.write_text(
        supervisor.read_text().replace(
            'if len(sys.argv) == 3 and sys.argv[1] == "--supervise":\n        _process_runner()\n',
            'if len(sys.argv) == 3 and sys.argv[1] == "--supervise":\n'
            "        _process_runner()\n"
            "        time.sleep(60)\n",
            1,
        ),
    )
    monkeypatch.setattr(agent, "__file__", str(supervisor))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", "import sys;sys.stdin.read()"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path)},
        deadline=3,
        input_text="x" * (4 * 1024 * 1024),
    )
    assert time.monotonic() - started < 20
    assert result.timed_out
    assert result.returncode == 1


@LINUX_ONLY
def test_progress_is_observed_while_child_is_still_alive(tmp_path):
    child = (
        "import os,pathlib,sys,time\n"
        "pathlib.Path('pid').write_text(str(os.getpid()))\n"
        'print(\'{"type":"system","subtype":"init"}\',flush=True)\n'
        "for _ in range(200):\n"
        " if pathlib.Path('ack').exists(): raise SystemExit(0)\n"
        " time.sleep(0.05)\n"
        "raise SystemExit(3)\n"
    )
    alive = []

    def emit(line):
        pid = int((tmp_path / "pid").read_text())
        os.kill(pid, 0)  # Raises if the child already exited.
        alive.append(line)
        (tmp_path / "ack").touch()

    result = run_process(
        [sys.executable, "-c", child],
        cwd=tmp_path,
        env={},
        deadline=20,
        observer=ProgressObserver(emit=emit),
    )
    assert result.returncode == 0, result.stderr
    assert len(alive) == 1
    assert "session started" in alive[0]


@LINUX_ONLY
def test_secret_split_across_child_writes_never_appears_live(tmp_path):
    secret = "fake-secret-split-value"  # noqa: S105 - fake redaction fixture.
    parts = [secret[:7], secret[7:15], secret[15:]]
    child = (
        "import sys,time\n"
        'line=\'{"type":"assistant","message":{"id":"a","content":'
        f'[{{"type":"text","text":"x {secret} y"}}]}}}}\\n\'\n'
        f"for start,end in {[(0, 40), (40, 46), (46, 57), (57, 400)]!r}:\n"
        " sys.stdout.write(line[start:end]);sys.stdout.flush();time.sleep(0.1)\n"
    )
    lines = []
    result = run_process(
        [sys.executable, "-c", child],
        cwd=tmp_path,
        env={},
        deadline=20,
        secrets=[secret],
        observer=ProgressObserver(emit=lines.append, secrets=[secret]),
    )
    assert result.returncode == 0, result.stderr
    assert parts[0] not in "\n".join(lines) or "[REDACTED]" in "\n".join(lines)
    assert secret not in "\n".join(lines)
    assert "x [REDACTED] y" in "\n".join(lines)
    assert secret not in result.stdout


@LINUX_ONLY
def test_observed_capture_keeps_complete_stdout(tmp_path):
    child = (
        "import sys,time\n"
        "for index in range(300):\n"
        ' print(\'{"type":"system","subtype":"other","n":%d}\' % index,flush=True)\n'
        " if index % 50 == 0: time.sleep(0.12)\n"
    )
    result = run_process(
        [sys.executable, "-c", child],
        cwd=tmp_path,
        env={},
        deadline=20,
        observer=ProgressObserver(emit=lambda _: None),
    )
    assert result.returncode == 0
    events = [json.loads(line) for line in result.stdout.split("\n") if line]
    assert [event["n"] for event in events] == list(range(300))


@LINUX_ONLY
def test_budget_stop_cleans_descendants_before_returning(tmp_path):
    lines = []
    observer = ProgressObserver(emit=lines.append, max_tokens=100)
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", _budget_child()],
        cwd=tmp_path,
        env={},
        deadline=25,
        observer=observer,
    )
    assert time.monotonic() - started < 10
    assert observer.exceeded
    assert result.returncode == -9
    assert not result.timed_out
    assert any("session token budget exceeded" in line for line in lines)
    time.sleep(1.3)
    assert not (tmp_path / "escaped").exists()


@LINUX_ONLY
def test_observer_failure_still_runs_descendant_cleanup(tmp_path):
    class Broken(ProgressObserver):
        def feed(self, data):  # noqa: ARG002 - failure before any parsing.
            msg = "observer boom"
            raise RuntimeError(msg)

    result = run_process(
        [sys.executable, "-c", _budget_child()],
        cwd=tmp_path,
        env={},
        deadline=25,
        observer=Broken(emit=lambda _: None),
    )
    assert result.returncode == -9
    assert "progress observer failed: RuntimeError" in result.stderr
    time.sleep(1.3)
    assert not (tmp_path / "escaped").exists()


def test_run_process_passes_observer_only_when_requested(monkeypatch, tmp_path):
    calls = []

    def strict(argv, *, cwd, env, deadline, stop_file, input_text, **extra):  # noqa: ARG001
        calls.append(extra)
        return ProcessResult(0, "", "")

    monkeypatch.setattr(agent, "_process_runner", lambda: strict)
    run_process(["x"], cwd=tmp_path, env={}, deadline=1)
    observer = ProgressObserver(emit=lambda _: None)
    run_process(["x"], cwd=tmp_path, env={}, deadline=1, observer=observer)
    assert calls == [{}, {"observer": observer}]


def _fake_runner(stream: bytes, calls: list, *, chunk=7):
    def runner(argv, *, cwd, env, deadline, stop_file, input_text, observer):  # noqa: ARG001
        calls.append(observer)
        for start in range(0, len(stream), chunk):
            observer.feed(stream[start : start + chunk])
        return ProcessResult(-9 if observer.stop_requested else 0, stream.decode(), "")

    return lambda: runner


def test_run_agent_reports_budget_error_with_safe_progress(
    monkeypatch,
    workspace,
    tmp_path,
):
    secret = "fake-contract-token"  # noqa: S105 - fake redaction fixture.
    leaked = BUDGET_EVENT.replace("working", f"working {secret}")
    stream = (leaked + "\n").encode()
    calls = []
    monkeypatch.setattr(agent, "_process_runner", _fake_runner(stream, calls))
    lines = []
    result = run_agent(
        config("http://127.0.0.1:9", "openai"),
        workspace=workspace,
        tool_bin=tmp_path / "bin",
        prompt="Fixture",
        runtime_dir=tmp_path / "runtime",
        max_session_tokens=100,
        progress=lines.append,
    )
    assert result.returncode == 1
    assert "session token budget exceeded" in result.stderr
    assert "unchanged tool retries" not in result.stderr
    assert not result.timed_out
    assert calls[0].max_tokens == 100
    assert secret not in "\n".join(lines)
    assert any("session token budget exceeded" in line for line in lines)
    # A later stage subtracts this count before it runs.
    assert result.reported_tokens == 100


def test_run_agent_default_limit_does_not_stop_below_threshold(
    monkeypatch,
    workspace,
    tmp_path,
):
    calls = []
    monkeypatch.setattr(
        agent,
        "_process_runner",
        _fake_runner((BUDGET_EVENT + "\n").encode(), calls),
    )
    result = run_agent(
        config("http://127.0.0.1:9", "openai"),
        workspace=workspace,
        tool_bin=tmp_path / "bin",
        prompt="Fixture",
        runtime_dir=tmp_path / "runtime",
        progress=lambda _: None,
    )
    assert result.returncode == 0
    assert "token budget" not in result.stderr
    assert calls[0].max_tokens == 20_000_000
    assert calls[0].tokens == 100
    assert result.reported_tokens == 100


def test_reported_tokens_default_to_zero_without_an_observer(tmp_path, monkeypatch):
    # Positional construction must stay valid for callers without an observer.
    assert ProcessResult(0, "", "").reported_tokens == 0
    monkeypatch.setattr(agent, "_process_runner", lambda: _local_cli_process)
    result = run_process(
        [sys.executable, "-c", "print('done')"],
        cwd=tmp_path,
        env={},
        deadline=20,
    )
    assert result.returncode == 0
    assert result.reported_tokens == 0


@pytest.mark.parametrize("limit", [0, -1, True, False, "5", 1.5, None])
def test_invalid_token_limits_reject_before_authentication(
    monkeypatch,
    workspace,
    tmp_path,
    limit,
):
    monkeypatch.setattr(agent, "_process_runner", lambda: None)
    with (
        endpoint("openai", tools=False) as (url, requests),
        pytest.raises(ConfigurationError, match="token limit"),
    ):
        run_agent(
            config(url, "openai", **{"llm-auth-token": "fake-first,fake-second"}),
            workspace=workspace,
            tool_bin=tmp_path / "bin",
            prompt="Fixture",
            runtime_dir=tmp_path / "runtime",
            max_session_tokens=limit,
        )
    assert requests == []
    assert not (tmp_path / "runtime").exists()


@LINUX_ONLY
def test_run_agent_budget_stops_owned_cli_without_orphans(workspace, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "qwen"
    fake.write_text(
        f"#!{sys.executable}\n"
        f"import os,sys,time\nos.chdir({str(tmp_path)!r})\n{_budget_child()}\n",
    )
    fake.chmod(0o755)
    lines = []
    result = run_agent(
        config("http://127.0.0.1:9", "openai"),
        workspace=workspace,
        tool_bin=bin_dir,
        prompt="Fixture",
        runtime_dir=tmp_path / "runtime",
        max_session_tokens=100,
        deadline=25,
        progress=lines.append,
    )
    assert result.returncode == 1
    assert "session token budget exceeded" in result.stderr
    assert not result.timed_out
    assert any("working" in line for line in lines)
    time.sleep(1.3)
    assert not (tmp_path / "escaped").exists()
