"""Lint queue compatibility with real actionlint and ShellCheck."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/auto_sync/lint_workflows.py"


@pytest.fixture
def lint(tmp_path, monkeypatch):
    tool_bin = os.environ.get("AUTO_SYNC_TOOL_BIN")
    if tool_bin:
        monkeypatch.setenv("PATH", tool_bin + os.pathsep + os.environ["PATH"])
    assert shutil.which("actionlint"), "Required pinned actionlint is unavailable"
    assert shutil.which("shellcheck"), "Required ShellCheck is unavailable"

    def run(source, *others):
        paths = []
        for index, content in enumerate((source, *others)):
            path = tmp_path / f"workflow-{index}.yml"
            path.write_text(content)
            paths.append(path)
        before = [path.read_bytes() for path in paths]
        result = subprocess.run(  # noqa: S603 - fixed helper and temporary fixtures.
            [sys.executable, str(SCRIPT), *map(str, paths)],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert [path.read_bytes() for path in paths] == before
        return result

    return run


def workflow(concurrency="", *, job=False, step="run: echo ok", runner="ubuntu-24.04"):
    scope = "" if job else concurrency
    nested = (
        ""
        if not job
        else "".join("    " + line + "\n" for line in concurrency.splitlines())
    )
    return (
        "name: Fixture\non: push\n"
        + scope
        + "jobs:\n  test:\n"
        + nested
        + f"    runs-on: {runner}\n    steps:\n      - {step}\n"
    )


@pytest.mark.parametrize("job", [False, True])
@pytest.mark.parametrize(
    "concurrency",
    [
        "concurrency:\n  group: fixture\n  queue: max\n",
        "concurrency:\n  group: fixture\n  queue: max\n  cancel-in-progress: false\n",
        "concurrency: {group: fixture, queue: 'single', cancel-in-progress: true}\n",
        "concurrency:\n  group: fixture\n  queue: single\n  cancel-in-progress: ${{ github.ref == 'refs/heads/main' }}\n",
        "concurrency: fixture\n",
        "",
    ],
)
def test_valid_queue_and_existing_concurrency(lint, concurrency, job):
    result = lint(workflow(concurrency, job=job))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("job", [False, True])
@pytest.mark.parametrize(
    "queue",
    ["false", "42", "null", "[]", "{}", "all", "MAX", "'${{ vars.QUEUE }}'"],
)
def test_invalid_queue_types_values_and_expressions(lint, job, queue):
    result = lint(
        workflow(f"concurrency:\n  group: fixture\n  queue: {queue}\n", job=job),
    )
    assert result.returncode != 0
    assert "queue" in result.stderr


@pytest.mark.parametrize(
    "cancel",
    [
        "true",
        "'false'",
        "null",
        "0",
        "no",
        "off",
        "'${{ false }}'",
        "${{ github.ref == 'main' }}",
    ],
)
def test_max_requires_absent_or_literal_false_cancellation(lint, cancel):
    result = lint(
        workflow(
            f"concurrency:\n  group: fixture\n  queue: max\n  cancel-in-progress: {cancel}\n",
        ),
    )
    assert result.returncode != 0
    assert "cancel-in-progress" in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        workflow("concurrency: {group: fixture, queue: max, queue: single}\n"),
        workflow("concurrency:\n  group: fixture\n  queue: max\n  'queue': single\n"),
        workflow().replace(
            "runs-on: ubuntu-24.04",
            "runs-on: ubuntu-24.04\n    runs-on: ubuntu-latest",
        ),
        workflow().replace("name: Fixture", "name: Fixture\nname: Other"),
    ],
)
def test_duplicate_keys_are_rejected(lint, source):
    result = lint(source)
    assert result.returncode != 0
    assert "duplicate" in result.stderr


def test_unrelated_actionlint_syntax_still_fails(lint):
    source = workflow("concurrency: {group: fixture, queue: max}\n")
    result = lint(source.replace("runs-on:", "runs-onn:"))
    assert result.returncode != 0
    assert "runs-onn" in result.stdout + result.stderr


def test_shellcheck_still_fails_and_preserves_script(lint):
    result = lint(
        workflow(
            "concurrency: {group: fixture, queue: max}\n",
            step="run: echo $missing",
        ),
    )
    assert result.returncode != 0
    assert "SC2086" in result.stdout + result.stderr


def test_unknown_field_is_not_removed_with_queue(lint):
    result = lint(workflow("concurrency: {group: fixture, queue: max, typo: false}\n"))
    assert result.returncode != 0
    assert "typo" in result.stdout + result.stderr


def test_queue_removal_does_not_change_aliased_fields(lint):
    source = workflow("concurrency: &shared {group: fixture, queue: max}\n")
    source = source.replace("jobs:", "permissions: *shared\njobs:")
    result = lint(source)
    assert result.returncode != 0
    assert 'scope "queue"' in result.stdout + result.stderr


def test_custom_runner_labels_use_project_config(lint, tmp_path):
    directory = tmp_path / ".github"
    directory.mkdir()
    (directory / "actionlint.yaml").write_text(
        "self-hosted-runner:\n  labels: [ubuntu-24.04-4x, ubuntu-24.04-8x]\n",
    )
    valid = workflow(
        "concurrency: {group: fixture, queue: max}\n",
        runner="ubuntu-24.04-4x",
    )
    result = lint(valid)
    assert result.returncode == 0, result.stdout + result.stderr
    result = lint(valid.replace("ubuntu-24.04-4x", "unknown-runner"))
    assert result.returncode != 0
    assert "unknown-runner" in result.stdout + result.stderr


@pytest.mark.parametrize("source", ["on: [\n", "---\non: push\n---\non: push\n"])
def test_malformed_yaml_never_reports_success(lint, source):
    result = lint(source)
    assert result.returncode != 0
    assert "workflow-0.yml" in result.stderr


def test_multiple_files_preserve_each_result(lint):
    valid = workflow("concurrency: {group: fixture, queue: max}\n")
    result = lint(valid, valid.replace("runs-on:", "runs-onn:"))
    assert result.returncode != 0
    assert "workflow-1.yml" in result.stdout + result.stderr


@pytest.mark.parametrize("binary", ["actionlint", "shellcheck"])
def test_missing_tools_never_report_success(tmp_path, monkeypatch, binary):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    other = "shellcheck" if binary == "actionlint" else "actionlint"
    tool_bin = os.environ.get("AUTO_SYNC_TOOL_BIN")
    lookup_path = (
        tool_bin + os.pathsep + os.environ["PATH"] if tool_bin else os.environ["PATH"]
    )
    tool = shutil.which(other, path=lookup_path)
    assert tool, f"Required {other} fixture tool is unavailable"
    (bin_dir / other).symlink_to(tool)
    monkeypatch.setenv("PATH", str(bin_dir))
    path = tmp_path / "workflow.yml"
    path.write_text(workflow())
    result = subprocess.run(  # noqa: S603 - fixed helper and temporary fixture.
        [sys.executable, str(SCRIPT), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert binary in result.stderr


def test_wrong_actionlint_version_never_reports_success(tmp_path, monkeypatch):
    shellcheck = shutil.which("shellcheck")
    assert shellcheck, "Required ShellCheck is unavailable"
    (tmp_path / "shellcheck").symlink_to(shellcheck)
    actionlint = tmp_path / "actionlint"
    actionlint.write_text("#!/bin/sh\nprintf '%s\\n' '0.0.0'\n")
    actionlint.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    path = tmp_path / "workflow.yml"
    path.write_text(workflow())
    result = subprocess.run(  # noqa: S603 - fixed helper and controlled version fixture.
        [sys.executable, str(SCRIPT), str(path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "pinned version" in result.stderr
