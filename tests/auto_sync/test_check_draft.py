# ruff: noqa: E402
"""The advisory draft checker reuses controller validators on trusted seeds."""

import json
import socket
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.auto_sync import assemble, proposal
from tools.auto_sync.check_draft import ADVISORY_NOTE, main

REVISION = "c" * 40
IDENTITY = {
    "repository": "gpustack/runner",
    "default_sha": "a" * 40,
    "head_sha": "a" * 40,
    "mode": "discover",
    "pr_number": None,
    "command_id": None,
    "command_digest": None,
}


def make_seed(tmp_path, stage):
    seed = tmp_path / ".autosync" / "seed"
    seed.mkdir(parents=True)
    if stage == "analysis":
        (seed / "identity.json").write_text(json.dumps(IDENTITY))
        (seed / "discovery.json").write_text(json.dumps(discovery()))
        (seed / "evidence.json").write_text(json.dumps(evidence()))
    else:
        (seed / "identity.json").write_text(json.dumps(IDENTITY))
        (seed / "permissions.json").write_text(
            json.dumps(
                {
                    "engine_prereleases": [],
                    "prerelease_packages": ["lmcache", "vllm-omni"],
                },
            ),
        )
    return seed


def discovery():
    found = []
    for backend, service in (
        ("cuda", "vllm"),
        ("cuda", "sglang"),
        ("rocm", "vllm"),
        ("rocm", "sglang"),
        ("cann", "vllm"),
        ("cann", "sglang"),
    ):
        found.append(
            {
                "subscription": f"{backend}/{service}",
                "status": "needs_update",
                "engine_version": "0.30.0" if service == "vllm" else "0.5.0",
                "plugin_version": "0.30.0rc1"
                if (backend, service) == ("cann", "vllm")
                else None,
            },
        )
    return found


def evidence():
    return {
        "vllm-project/vllm@0.30.0": {"revision": REVISION},
        "sgl-project/sglang@0.5.0": {"revision": REVISION},
        "vllm-project/vllm-ascend@0.30.0rc1": {"revision": REVISION},
    }


def fixture(name):
    return json.loads(
        (Path(__file__).parent / "fixtures/proposals" / name).read_text(),
    )


def analysis_draft():
    raw = fixture("analysis.json")
    raw["identity"] = IDENTITY
    for candidate in raw["candidates"]:
        if candidate["status"] == "analyzed":
            candidate["source_revision"] = REVISION
    return raw


def proposal_draft(tmp_path):
    raw = fixture("ready.json")
    raw["identity"] = IDENTITY
    patch = raw["groups"][0].pop("patch")
    (tmp_path / "cuda-vllm.patch").write_text(patch)
    raw["groups"][0]["patch_file"] = "cuda-vllm.patch"
    return raw


def run_checker(monkeypatch, capsys, stage, draft_text):
    monkeypatch.setattr(sys, "stdin", StringIO(draft_text))
    code = main(["--stage", stage])
    out = capsys.readouterr().out
    return code, out.splitlines()


def test_valid_analysis_draft_prints_valid_and_the_advisory_note(
    tmp_path,
    monkeypatch,
    capsys,
):
    make_seed(tmp_path, "analysis")
    monkeypatch.chdir(tmp_path)
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "analysis",
        json.dumps(analysis_draft()),
    )
    assert code == 0
    assert lines[0] == "VALID"
    assert lines[1] == ADVISORY_NOTE


def test_valid_proposal_draft_inlines_the_patch_file(
    tmp_path,
    monkeypatch,
    capsys,
):
    make_seed(tmp_path, "proposal")
    monkeypatch.chdir(tmp_path)
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "proposal",
        json.dumps(proposal_draft(tmp_path)),
    )
    assert code == 0
    assert lines[0] == "VALID"
    assert lines[1] == ADVISORY_NOTE


def test_validator_rejection_is_reported_as_data(tmp_path, monkeypatch, capsys):
    make_seed(tmp_path, "analysis")
    monkeypatch.chdir(tmp_path)
    draft = analysis_draft()
    draft["candidates"][0]["status"] = "ready"
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "analysis",
        json.dumps(draft),
    )
    assert code == 0
    assert lines[0].startswith("INVALID: ")
    assert "invalid analysis status" in lines[0]


def test_unparseable_draft_is_a_completed_check(tmp_path, monkeypatch, capsys):
    make_seed(tmp_path, "analysis")
    monkeypatch.chdir(tmp_path)
    for text in ("Certainly!\n```json\n{}\n```", ""):
        code, lines = run_checker(monkeypatch, capsys, "analysis", text)
        assert code == 0
        assert lines[0].startswith("INVALID: invalid JSON: ")


def test_parse_gate_rejects_what_the_controller_rejects(
    tmp_path,
    monkeypatch,
    capsys,
):
    make_seed(tmp_path, "analysis")
    monkeypatch.chdir(tmp_path)
    cases = [
        ('{"a": 1, "a": 2}', "duplicate JSON key"),
        ('{"a": NaN}', "nonfinite"),
        ("[1, 2]", "proposal output must be an object"),
    ]
    for text, fragment in cases:
        code, lines = run_checker(monkeypatch, capsys, "analysis", text)
        assert code == 0
        assert lines[0].startswith("INVALID: ")
        assert fragment in lines[0]


def test_wrong_seed_shape_fails_closed(tmp_path, monkeypatch, capsys):
    seed = make_seed(tmp_path, "analysis")
    seed.joinpath("identity.json").write_text("null")
    monkeypatch.chdir(tmp_path)
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "analysis",
        json.dumps(analysis_draft()),
    )
    assert code == 3
    assert lines[0].startswith("CHECKER UNAVAILABLE: identity.json")


def test_missing_seed_directory_fails_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "analysis",
        json.dumps(analysis_draft()),
    )
    assert code == 3
    assert lines[0].startswith("CHECKER UNAVAILABLE: ")


def test_malformed_seed_file_fails_closed(tmp_path, monkeypatch, capsys):
    seed = make_seed(tmp_path, "analysis")
    seed.joinpath("identity.json").write_text("not json")
    monkeypatch.chdir(tmp_path)
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "analysis",
        json.dumps(analysis_draft()),
    )
    assert code == 3
    assert lines[0].startswith("CHECKER UNAVAILABLE: ")


def test_no_network_access_for_a_full_valid_check(
    tmp_path,
    monkeypatch,
    capsys,
):
    make_seed(tmp_path, "analysis")

    def blocked(*_args, **_kwargs):
        msg = "the checker must not touch the network"
        raise AssertionError(msg)

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.chdir(tmp_path)
    code, lines = run_checker(
        monkeypatch,
        capsys,
        "analysis",
        json.dumps(analysis_draft()),
    )
    assert code == 0
    assert lines[0] == "VALID"


def test_repeated_failing_checks_keep_exiting_zero(tmp_path, monkeypatch, capsys):
    make_seed(tmp_path, "analysis")
    monkeypatch.chdir(tmp_path)
    draft = analysis_draft()
    draft["candidates"][0]["status"] = "ready"
    for _ in range(3):
        code, lines = run_checker(
            monkeypatch,
            capsys,
            "analysis",
            json.dumps(draft),
        )
        assert code == 0
        assert lines[0].startswith("INVALID: ")


def test_checker_verdict_matches_the_direct_validator(
    tmp_path,
    monkeypatch,
    capsys,
):
    make_seed(tmp_path, "analysis")
    make_seed(tmp_path / "proposal-run", "proposal")
    invalid_analysis = analysis_draft()
    invalid_analysis["candidates"][0]["status"] = "ready"
    invalid_proposal = fixture("ready.json")
    invalid_proposal.pop("groups")
    cases = [
        ("analysis", analysis_draft(), True),
        ("analysis", invalid_analysis, False),
        ("proposal", proposal_draft(tmp_path / "proposal-run"), True),
        ("proposal", invalid_proposal, False),
    ]
    for stage, draft, valid in cases:
        monkeypatch.chdir(
            tmp_path if stage == "analysis" else tmp_path / "proposal-run",
        )
        _, lines = run_checker(monkeypatch, capsys, stage, json.dumps(draft))
        try:
            if stage == "analysis":
                proposal.validate_analysis(
                    draft,
                    IDENTITY,
                    found=discovery(),
                    evidence=evidence(),
                )
            else:
                proposal.validate_proposal(
                    assemble.assemble(draft, Path.cwd()),
                    IDENTITY,
                    engine_prereleases=set(),
                    prerelease_packages={"lmcache", "vllm-omni"},
                )
            expected = "VALID"
        except proposal.ProposalError as exc:
            expected = f"INVALID: {exc}"
        assert lines[0] == expected
        assert (expected == "VALID") == valid
