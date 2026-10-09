"""Proposal assembly inlines patch files as data without judging the proposal."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.auto_sync.assemble import assemble_file  # noqa: E402
from tools.auto_sync.proposal import ProposalError  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures/proposals/ready.json"


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _split(tmp_path, data, name="a.patch"):
    """Move the first group's patch into a file and return the draft path."""
    draft = copy.deepcopy(data)
    group = draft["groups"][0]
    (tmp_path / name).write_bytes(group.pop("patch").encode("utf-8"))
    group["patch_file"] = name
    path = tmp_path / "draft.json"
    _write(path, draft)
    return path, draft


def test_ready_fixture_round_trips(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft, _ = _split(tmp_path, original)
    out = tmp_path / "out.json"
    assemble_file(draft, out)
    assert json.loads(out.read_text(encoding="utf-8")) == original


def test_relative_path_uses_draft_directory(tmp_path, monkeypatch):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sub = tmp_path / "sub"
    sub.mkdir()
    draft, _ = _split(sub, original)
    monkeypatch.chdir(tmp_path)
    assemble_file(draft, tmp_path / "out.json")
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert result == original


def test_special_characters_round_trip(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = '+path C:\\dir\\n "quoted" \\" 你好 😀 \\u0041\n\r\n'
    original["groups"][0]["patch"] = text
    draft, _ = _split(tmp_path, original)
    assemble_file(draft, tmp_path / "out.json")
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert result["groups"][0]["patch"] == text
    assert "patch_file" not in result["groups"][0]


def test_inline_patch_and_other_candidates_are_preserved(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft = tmp_path / "draft.json"
    _write(draft, original)
    assemble_file(draft, tmp_path / "out.json")
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert result == original
    statuses = {c["status"] for c in result["candidates"]}
    assert {"blocked", "failed", "unchanged"} <= statuses


def test_blocked_group_is_not_promoted(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    original["groups"][0]["status"] = "blocked"
    draft, _ = _split(tmp_path, original)
    assemble_file(draft, tmp_path / "out.json")
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert result["groups"][0]["status"] == "blocked"


def _expect_failure(tmp_path, draft):
    out = tmp_path / "out.json"
    with pytest.raises(ProposalError):
        assemble_file(draft, out)
    assert not out.exists()


def test_both_fields_fail(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft, data = _split(tmp_path, original)
    data["groups"][0]["patch"] = original["groups"][0]["patch"]
    _write(draft, data)
    _expect_failure(tmp_path, draft)


@pytest.mark.parametrize("value", [None, 1, ["a.patch"], {"x": "y"}, True])
def test_non_string_patch_file_fails(tmp_path, value):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft, data = _split(tmp_path, original)
    data["groups"][0]["patch_file"] = value
    _write(draft, data)
    _expect_failure(tmp_path, draft)


def test_missing_file_fails(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft, data = _split(tmp_path, original)
    data["groups"][0]["patch_file"] = "missing.patch"
    _write(draft, data)
    _expect_failure(tmp_path, draft)


def test_invalid_utf8_patch_fails(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft, _ = _split(tmp_path, original)
    (tmp_path / "a.patch").write_bytes(b"\xff\xfe")
    _expect_failure(tmp_path, draft)


def test_duplicate_json_key_fails(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    _expect_failure(tmp_path, draft)


def test_cli_writes_json(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    draft, _ = _split(tmp_path, original)
    out = tmp_path / "out.json"
    done = subprocess.run(  # noqa: S603 - fixed local CLI and controlled fixture paths.
        [
            sys.executable,
            "-m",
            "tools.auto_sync.assemble",
            "--draft",
            str(draft),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(out.read_text(encoding="utf-8")) == original


def test_cli_failure_is_nonzero_without_output(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    out = tmp_path / "out.json"
    done = subprocess.run(  # noqa: S603 - fixed local CLI and controlled fixture paths.
        [
            sys.executable,
            "-m",
            "tools.auto_sync.assemble",
            "--draft",
            str(draft),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert "duplicate JSON key" in done.stderr
    assert not out.exists()
