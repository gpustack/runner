"""Check portable instruction discovery with Git and the pinned, offline CLI."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_agent import FIXTURES, config, endpoint, tool_bin  # noqa: F401

from tools.auto_sync.agent import run_agent

ROOT = Path(__file__).resolve().parents[2]
SKILL = Path(".agents/skills/runner-release-sync/SKILL.md")


def git(repo, *args):
    executable = shutil.which("git")
    assert executable
    return subprocess.run(  # noqa: S603 - arguments are fixed test inputs.
        [executable, "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env={"PATH": os.environ["PATH"], "HOME": str(repo)},
    )


def test_canonical_skill_link_stays_inside_repository():
    link = ROOT / ".claude/skills"
    assert link.is_symlink()
    assert not link.readlink().is_absolute()
    assert link.resolve() == ROOT / ".agents/skills"
    assert (link / "runner-release-sync/SKILL.md").read_text() == (
        ROOT / SKILL
    ).read_text()


def test_git_tracks_link_without_local_claude_content(tmp_path):
    shutil.copy(ROOT / ".gitignore", tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".agents/skills").mkdir(parents=True)
    link = tmp_path / ".claude/skills"
    link.symlink_to("../.agents/skills")
    local = [
        ".claude/handoffs/private.md",
        ".claude/specs/private.md",
        ".claude/worktrees/private/README.md",
        ".claude/settings.local.json",
    ]
    for name in local:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("local content\n")
    assert git(tmp_path, "init", "--quiet").returncode == 0
    assert git(tmp_path, "add", ".").returncode == 0
    tracked = git(tmp_path, "ls-files", "--stage").stdout
    assert "120000 " in tracked
    assert "\t.claude/skills\n" in tracked
    assert all(name not in tracked for name in local)
    assert git(tmp_path, "show", ":.claude/skills").stdout == "../.agents/skills"
    assert all((tmp_path / name).read_text() == "local content\n" for name in local)


def test_old_blanket_ignore_prevents_link_tracking(tmp_path):
    (tmp_path / ".gitignore").write_text(".claude/\n")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".agents/skills").mkdir(parents=True)
    (tmp_path / ".claude/skills").symlink_to("../.agents/skills")
    assert git(tmp_path, "init", "--quiet").returncode == 0
    result = git(tmp_path, "add", ".claude/skills")
    assert result.returncode != 0
    assert git(tmp_path, "ls-files", ".claude/skills").stdout == ""


@pytest.mark.parametrize("relative", ["AGENTS.md", str(SKILL), "README.md"])
def test_instruction_and_overview_links_resolve(relative):
    source = ROOT / relative
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", source.read_text())
    assert links
    for target in links:
        if "://" in target or target.startswith("#"):
            continue
        destination = (source.parent / target.split("#", 1)[0]).resolve()
        assert destination.is_relative_to(ROOT)
        assert destination.exists(), (relative, target)


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_real_cli_loads_canonical_instructions_skill_and_mcp(
    tool_bin,  # noqa: F811 - pytest requests the imported pinned-tool fixture.
    tmp_path,
    protocol,
):
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(ROOT / "AGENTS.md", project)
    shutil.copytree(ROOT / SKILL.parent, project / SKILL.parent)
    (project / ".claude").mkdir()
    (project / ".claude/skills").symlink_to("../.agents/skills")
    calls = [
        ("skill", {"skill": "runner-release-sync"}),
        ("mcp__fixture__research", {}),
    ]
    with endpoint(protocol, calls=calls) as (url, requests):
        result = run_agent(
            config(url, protocol),
            workspace=project,
            tool_bin=tool_bin,
            prompt="Load runner-release-sync and read the fixture MCP evidence. Return an assessment.",
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
    assert len(requests) == 3, result.stderr + result.stdout
    instructions = (ROOT / "AGENTS.md").read_text().strip()
    skill_body = (ROOT / SKILL).read_text().split("---", 2)[2].strip()
    assert json.dumps(instructions)[1:-1] in json.dumps(requests[0]["body"])
    assert json.dumps(skill_body)[1:-1] in json.dumps(requests[1]["body"])
    assert "MCP_EVIDENCE_LOADED" in json.dumps(requests[2]["body"])
    for request in requests:
        names = {
            tool.get("name", tool.get("function", {}).get("name"))
            for tool in request["body"]["tools"]
        }
        assert not names.intersection({"ask_user_question", "enter_plan_mode", "agent"})
