"""Run the pinned Qwen once, with isolated settings and a process-group deadline."""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.auto_sync.model import (
    ConfigurationError,
    ModelConfig,
    select_token,
)

# Remove every built-in route to questions, planning, agents, or persistent work.
DISABLED_TOOLS = [
    "ask_user_question",
    "enter_plan_mode",
    "exit_plan_mode",
    "agent",
    "create_sub_session",
    "list_agents",
    "team_create",
    "team_delete",
    "team_plan_approval",
    "request_shutdown",
    "send_message",
    "workflow",
    "advisor",
    "cron_create",
    "cron_list",
    "cron_delete",
    "loop_wakeup",
    "monitor",
    "enter_worktree",
    "exit_worktree",
    "propose_goal",
    "update_goal",
]


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _process_runner():
    if sys.platform != "linux":
        msg = "Agent process supervision requires Linux"
        raise ConfigurationError(msg)
    return _linux_process


def _supervise(request: dict) -> dict:
    """Adopt orphaned descendants in this dedicated Linux process only."""
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_CHILD_SUBREAPER: detached and double-forked children stay ours.
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        msg = "Cannot enable Linux child subreaper"
        raise OSError(ctypes.get_errno(), msg)
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    children.read_text()  # Check procfs before launching any agent process.
    with tempfile.TemporaryFile() as input_stream:
        input_stream.write(request["input_text"].encode("utf-8"))
        input_stream.seek(0)
        process = subprocess.Popen(  # noqa: S603 - trusted controller argv.
            request["argv"],
            stdin=input_stream,
        )
    expires = time.monotonic() + request["deadline"]
    stop_file = Path(request["stop_file"]) if request["stop_file"] else None
    timed_out = False
    try:
        while process.poll() is None:
            timed_out = time.monotonic() >= expires
            if timed_out or (stop_file and stop_file.exists()):
                break
            time.sleep(min(0.02, max(0, expires - time.monotonic())))
    finally:
        # Kill direct children; their children are then adopted and killed too.
        # Do not reap unrelated controller children or inspect host environments.
        cleanup_expires = time.monotonic() + 2
        cleaned = False
        while time.monotonic() < cleanup_expires:
            for value in children.read_text().split():
                with contextlib.suppress(ProcessLookupError):
                    os.kill(int(value), signal.SIGKILL)
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                cleaned = True
                break
            if pid == process.pid:
                process.returncode = os.waitstatus_to_exitcode(status)
            if pid == 0:
                time.sleep(0.01)
    return {
        "returncode": process.returncode if cleaned else 1,
        "timed_out": timed_out,
        "cleaned": cleaned,
    }


def _linux_process(argv, *, cwd, env, deadline, stop_file, input_text):
    # Regular files cannot leave communicate() waiting on an orphan's pipe.
    with (
        tempfile.TemporaryFile() as stdout,
        tempfile.TemporaryFile() as stderr,
        tempfile.TemporaryFile() as status,
    ):
        process = subprocess.Popen(  # noqa: S603 - fixed supervisor and trusted argv.
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--supervise",
                str(status.fileno()),
            ],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            pass_fds=(status.fileno(),),
        )
        request = json.dumps(
            {
                "argv": argv,
                "deadline": deadline,
                "stop_file": str(stop_file) if stop_file else None,
                "input_text": input_text,
            },
        ).encode()
        result = {"returncode": 1, "timed_out": False, "cleaned": False}
        try:
            process.communicate(request, timeout=deadline + 4)
            status.seek(0)
            if process.returncode == 0:
                result = json.load(status)
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)
        stdout.seek(0)
        stderr.seek(0)
        out = stdout.read(os.fstat(stdout.fileno()).st_size).decode(errors="replace")
        err = stderr.read(os.fstat(stderr.fileno()).st_size).decode(errors="replace")
        if not result["cleaned"]:
            err += "\nauto-sync: process cleanup could not be confirmed\n"
        return ProcessResult(result["returncode"], out, err, result["timed_out"])


def run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
    secrets: list[str] | tuple[str, ...] = (),
    stop_file: Path | None = None,
    input_text: str = "",
) -> ProcessResult:
    """Provide finite stdin with EOF and bound execution plus orphan cleanup."""
    if deadline <= 0:
        msg = "The process deadline must be positive"
        raise ConfigurationError(msg)
    result = _process_runner()(
        argv,
        cwd=cwd,
        env=env,
        deadline=deadline,
        stop_file=stop_file,
        input_text=input_text,
    )
    stdout, stderr = result.stdout, result.stderr
    redactions = {
        value
        for secret in secrets
        if secret
        for value in (secret, json.dumps(secret)[1:-1])
    }
    for secret in sorted(redactions, key=len, reverse=True):
        stdout, stderr = (
            stdout.replace(secret, "[REDACTED]"),
            stderr.replace(secret, "[REDACTED]"),
        )
    if result.timed_out:
        stderr += "\nauto-sync: outer process deadline exceeded\n"
    return ProcessResult(result.returncode, stdout, stderr, result.timed_out)


def tool_guard(event: dict, state: Path) -> dict:
    """Bound trusted shell calls and stop unchanged failures after two retries."""
    if event.get("hook_event_name") == "PreToolUse":
        denied = state.with_suffix(".failed").exists()
        if event.get("tool_name") == "run_shell_command":
            parameters = event.get("tool_input", {})
            timeout = parameters.get("timeout", 300000)
            denied = (
                denied
                or parameters.get("is_background", False)
                or type(timeout) not in {int, float}
                or not 0 < timeout <= 300000
            )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny" if denied else "allow",
                "permissionDecisionReason": "Commands must be foreground and bounded to 300 seconds",
            },
        }
    if event.get("hook_event_name") != "PostToolUseFailure":
        return {}
    identity = hashlib.sha256(
        json.dumps(
            [event.get("tool_name"), event.get("tool_input")],
            sort_keys=True,
        ).encode(),
    ).hexdigest()
    with state.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        failures = json.loads(stream.read() or "{}")
        failures[identity] = failures.get(identity, 0) + 1
        stream.seek(0)
        stream.truncate()
        json.dump(failures, stream)
    if failures[identity] >= 3:
        state.with_suffix(".failed").write_text("Repeated unchanged tool failure")
        return {
            "continue": False,
            "stopReason": "Repeated unchanged tool failure; two retries exhausted",
        }
    return {}


def github_mcp(tool_bin: Path, token: str) -> dict:
    """Use a native stdio server with read-only research tools."""
    if not token.strip():
        msg = "A GitHub research token is required"
        raise ConfigurationError(msg)
    return {
        "github": {
            "command": str(tool_bin / "github-mcp-server"),
            "args": [
                "stdio",
                "--read-only",
                "--toolsets",
                "repos,pull_requests,issues",
            ],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
            "trust": True,
            "timeout": 30000,
        },
    }


def run_agent(
    config: ModelConfig,
    *,
    workspace: Path,
    tool_bin: Path,
    prompt: str,
    runtime_dir: Path,
    mcp_servers: dict | None = None,
    deadline: float = 2700,
    max_turns: int = 60,
    max_tool_calls: int = 180,
    wall_time: int = 2400,
) -> ProcessResult:
    """
    The caller supplies a frozen-policy workspace, never raw PR settings.

    Candidate validation and publication run separately without these credentials.
    The caller must validate the returned assessment; exit zero is not acceptance.
    """
    _process_runner()  # Reject unsupported hosts before token probes or settings.
    workspace, runtime_dir, tool_bin = (
        workspace.resolve(),
        runtime_dir.resolve(),
        tool_bin.resolve(),
    )
    if runtime_dir.is_relative_to(workspace):
        msg = "Runtime settings must remain outside the workspace"
        raise ConfigurationError(msg)
    if not prompt.strip() or not (workspace / "AGENTS.md").is_file():
        msg = "Task and trusted AGENTS.md are required"
        raise ConfigurationError(msg)
    # Qwen 0.25.0 truncates stdin above 8 MiB; never lose frozen task context.
    if len(prompt.encode("utf-8")) > 8 * 1024 * 1024:
        msg = "Agent prompt exceeds the pinned CLI stdin limit"
        raise ConfigurationError(msg)
    # Reject automatic startup configuration instead of trusting its precedence.
    for name in (
        ".qwen",
        ".env",
        ".mcp.json",
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        if (workspace / name).exists() or (workspace / name).is_symlink():
            msg = (
                "Untrusted workspace configuration must be removed before agent startup"
            )
            raise ConfigurationError(msg)
    if max_turns <= 0 or max_tool_calls <= 0 or wall_time <= 0:
        msg = "Agent limits must be positive"
        raise ConfigurationError(msg)
    token = select_token(
        config,
        mask=(lambda value: print("::add-mask::" + value))
        if os.environ.get("GITHUB_ACTIONS") == "true"
        else lambda _: None,
    )
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = runtime_dir / "home"
    home.mkdir(mode=0o700)
    qwen_home = home / ".qwen"
    qwen_home.mkdir(mode=0o700)
    guard_state = runtime_dir / "tool-failures.json"
    guard_command = shlex.join(
        [sys.executable, str(Path(__file__).resolve()), "--guard", str(guard_state)],
    )
    settings = {
        "security": {"auth": {"selectedType": config.protocol}},
        "model": {
            "name": config.model,
            "maxSessionTurns": max_turns,
            "maxToolCalls": max_tool_calls,
            "maxWallTimeSeconds": wall_time,
        },
        "modelProviders": {
            config.protocol: [
                {
                    "id": config.model,
                    "name": config.model,
                    "envKey": "AUTO_SYNC_MODEL_TOKEN",
                    "baseUrl": config.base_url,
                    "generationConfig": config.generation_config(token),
                },
            ],
        },
        "context": {"fileName": ["AGENTS.md"]},
        "tools": {
            "disabled": DISABLED_TOOLS,
            "visible": ["skill"],
            "shell": {"enableInteractiveShell": False, "defaultTimeoutMs": 300000},
        },
        "skills": {"disabledLevels": ["user", "extension", "bundled"]},
        "memory": {
            "enableManagedAutoMemory": False,
            "enableManagedAutoDream": False,
            "enableAutoSkill": False,
            "enableTeamMemory": False,
        },
        "disableAllHooks": False,
        "hooks": {
            event: [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": guard_command, "timeout": 5000},
                    ],
                },
            ]
            for event in ("PreToolUse", "PostToolUseFailure")
        },
        "telemetry": {"enabled": False},
        "mcpServers": {
            name: {**server, "alwaysLoadTools": True}
            for name, server in (mcp_servers or {}).items()
        },
    }
    settings_path = qwen_home / "settings.json"
    settings_path.write_text(json.dumps(settings))
    settings_path.chmod(0o600)
    empty = runtime_dir / "empty.json"
    empty.write_text("{}")
    env = {
        "PATH": str(tool_bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "QWEN_HOME": str(qwen_home),
        "TMPDIR": str(runtime_dir),
        "QWEN_CODE_SYSTEM_SETTINGS_PATH": str(empty),
        "QWEN_CODE_SYSTEM_DEFAULTS_PATH": str(empty),
        "AUTO_SYNC_MODEL_TOKEN": token,
        "QWEN_CODE_SKIP_UPDATE_CHECK_ONCE": "1",
        "CI": "true",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
        "SSH_ASKPASS": "/usr/bin/false",
        "GIT_EDITOR": "true",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/dev/null",
        "PIP_NO_INPUT": "1",
        "UV_NO_PROGRESS": "1",
        "npm_config_yes": "true",
        "DEBIAN_FRONTEND": "noninteractive",
    }
    argv = [
        str(tool_bin / "qwen"),
        "--auth-type",
        config.protocol,
        "--model",
        config.model,
        "--approval-mode",
        "yolo",
        "--chat-recording=false",
        "--advisor",
        "off",
        "--output-format",
        "json",
        "--max-session-turns",
        str(max_turns),
        "--max-tool-calls",
        str(max_tool_calls),
        "--max-wall-time",
        str(wall_time),
        "--prompt",
        "Follow the task supplied on stdin.",
    ]
    secrets = [*config.tokens]
    for server in (mcp_servers or {}).values():
        secrets.extend(server.get("env", {}).values())
    try:
        result = run_process(
            argv,
            cwd=workspace,
            env=env,
            deadline=deadline,
            secrets=secrets,
            stop_file=guard_state.with_suffix(".failed"),
            input_text=prompt,
        )
        if guard_state.with_suffix(".failed").exists():
            return ProcessResult(
                1,
                result.stdout,
                result.stderr + "\nauto-sync: unchanged tool retries exhausted\n",
                result.timed_out,
            )
        return result
    finally:
        settings_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--supervise":
        _process_runner()
        with os.fdopen(int(sys.argv[2]), "w") as status_stream:
            json.dump(_supervise(json.load(sys.stdin)), status_stream)
        raise SystemExit(0)
    if len(sys.argv) != 3 or sys.argv[1] != "--guard":
        msg = "Usage: agent.py --guard STATE"
        raise SystemExit(msg)
    print(json.dumps(tool_guard(json.load(sys.stdin), Path(sys.argv[2]))))
