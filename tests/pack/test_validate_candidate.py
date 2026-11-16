"""Behavior tests for .auto-sync/checks/validate_candidate.py scope and proposal rules."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

# Subprocess calls invoke fixed git and bash binaries on temporary candidate directories.
# ruff: noqa: S603

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / ".auto-sync" / "checks" / "validate_candidate.py"
SCRIPT_PATH = REPO_ROOT / ".auto-sync" / "checks" / "validate_candidate.sh"

SPEC = importlib.util.spec_from_file_location("validate_candidate", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
vc_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vc_mod)

CANDIDATE_COPY_PATHS = (
    ".auto-sync",
    "README.md",
    "docs",
    "gpustack_runner",
    "pack",
)


def _ignore_copy(_src: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".DS_Store"}}


def _build_candidate_workspace(tmp_path: Path, *, with_git: bool = True) -> Path:
    cand = tmp_path / "candidate"
    cand.mkdir()
    for rel in CANDIDATE_COPY_PATHS:
        src = REPO_ROOT / rel
        dst = cand / rel
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=False, ignore=_ignore_copy)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    if with_git:
        git_bin = shutil.which("git")
        assert git_bin is not None
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test Bot",
            "GIT_AUTHOR_EMAIL": "bot@gpustack.ai",
            "GIT_COMMITTER_NAME": "Test Bot",
            "GIT_COMMITTER_EMAIL": "bot@gpustack.ai",
        }
        subprocess.run(
            [git_bin, "init", "-q"],
            cwd=cand,
            env=git_env,
            check=True,
        )
        subprocess.run(
            [git_bin, "add", "-A"],
            cwd=cand,
            env=git_env,
            check=True,
        )
        subprocess.run(
            [git_bin, "commit", "-q", "-m", "baseline"],
            cwd=cand,
            env=git_env,
            check=True,
        )
    return cand


@pytest.fixture(scope="module")
def baseline_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("candidate_template")
    return _build_candidate_workspace(base, with_git=True)


def _clone_candidate(baseline_template: Path, tmp_path: Path) -> Path:
    cand = tmp_path / "candidate"
    shutil.copytree(baseline_template, cand, symlinks=True)
    return cand


def test_repo_control_plane_layout_and_skill_retirement() -> None:
    assert not (REPO_ROOT / ".autosync").exists()
    assert (REPO_ROOT / ".auto-sync" / "proposal.json").is_file()
    assert not (REPO_ROOT / ".agents" / "skills" / "runner-release-sync").exists()
    assert (REPO_ROOT / ".agents" / "skills" / "runner-release" / "SKILL.md").is_file()

    instructions_bytes = (REPO_ROOT / ".auto-sync" / "instructions.md").read_bytes()
    assert len(instructions_bytes) <= 24576


def test_clean_baseline_passes_validator_and_shell_entrypoint(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    vc_mod.validate_candidate(cand)

    bash_bin = shutil.which("bash") or "/bin/bash"
    res = subprocess.run(
        [bash_bin, str(SCRIPT_PATH)],
        cwd=cand,
        env={**os.environ, "LOOPWRIGHT_CANDIDATE_DIR": str(cand)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr


def test_modifying_proposal_json_inside_control_root_is_allowed(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    proposal_file = cand / ".auto-sync" / "proposal.json"
    payload = json.loads(proposal_file.read_text(encoding="utf-8"))
    payload["summary"] = "Updated proposal summary inside .auto-sync/proposal.json."
    proposal_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    vc_mod.validate_candidate(cand)


def test_classify_scope_path_defaults_fail_closed_without_proposal_carveout(
    baseline_template: Path,
) -> None:
    writable, protected, _ = vc_mod.load_effective_scope(baseline_template)
    assert (
        vc_mod.classify_scope_path(".auto-sync/proposal.json", writable, protected)
        == "protected"
    )
    assert (
        vc_mod.classify_scope_path(
            ".auto-sync/proposal.json",
            writable,
            protected,
            proposal_path=".auto-sync/proposal.json",
        )
        == "writable"
    )
    assert (
        vc_mod.classify_scope_path(
            ".auto-sync/proposal.json/nested.json",
            writable,
            protected,
            proposal_path=".auto-sync/proposal.json",
        )
        == "protected"
    )
    assert (
        vc_mod.classify_scope_path(
            ".auto-sync/instructions.md",
            writable,
            protected,
            proposal_path=".auto-sync/proposal.json",
        )
        == "protected"
    )


@pytest.mark.parametrize(
    "protected_rel",
    [
        ".auto-sync/instructions.md",
        ".auto-sync/taskpack.yaml",
        ".auto-sync/checks/validate_candidate.sh",
        ".auto-sync/memory/.gitkeep",
    ],
)
def test_modifying_control_plane_files_in_git_workspace_is_rejected(
    baseline_template: Path,
    tmp_path: Path,
    protected_rel: str,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    target = cand / protected_rel
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# unauthorized edit\n",
        encoding="utf-8",
    )

    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)


def test_legacy_autosync_directory_or_symlink_is_rejected(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")
    legacy_dir = cand / ".autosync"
    legacy_dir.mkdir()
    (legacy_dir / "proposal.json").write_text("{}", encoding="utf-8")

    with pytest.raises(
        vc_mod.ValidationError,
        match=r"legacy \.autosync path must not exist",
    ):
        vc_mod.validate_candidate(cand)

    shutil.rmtree(legacy_dir)
    legacy_dir.symlink_to(cand / ".auto-sync")
    with pytest.raises(
        vc_mod.ValidationError,
        match=r"legacy \.autosync path must not exist",
    ):
        vc_mod.validate_candidate(cand)


def test_unexpected_entries_or_symlinks_under_control_root_are_rejected(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")

    extra_file = cand / ".auto-sync" / "extra.json"
    extra_file.write_text("{}", encoding="utf-8")
    with pytest.raises(
        vc_mod.ValidationError,
        match=r"\.auto-sync/ contains unexpected entries",
    ):
        vc_mod.validate_candidate(cand)
    extra_file.unlink()

    proposal_file = cand / ".auto-sync" / "proposal.json"
    outside = tmp_path / "outside.json"
    outside.write_text(proposal_file.read_text(encoding="utf-8"), encoding="utf-8")

    ds_store_link = cand / ".auto-sync" / ".DS_Store"
    ds_store_link.symlink_to(outside)
    with pytest.raises(vc_mod.ValidationError, match="symlink not allowed"):
        vc_mod.validate_candidate(cand)
    ds_store_link.unlink()

    hardlink_target = tmp_path / "hardlinked_proposal.json"
    os.link(proposal_file, hardlink_target)
    with pytest.raises(vc_mod.ValidationError, match="must not be hardlinked"):
        vc_mod.validate_candidate(cand)
    hardlink_target.unlink()

    proposal_file.unlink()
    proposal_file.symlink_to(outside)
    with pytest.raises(vc_mod.ValidationError, match="symlink not allowed"):
        vc_mod.validate_candidate(cand)


def test_proposal_unknown_top_level_keys_and_spoofed_unchanged_versions_rejected(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    proposal_file = cand / ".auto-sync" / "proposal.json"
    original = json.loads(proposal_file.read_text(encoding="utf-8"))

    with_upstreams = {**original, "upstreams": {"vllm": "v0.34.0"}}
    proposal_file.write_text(
        json.dumps(with_upstreams, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(vc_mod.ValidationError, match="unknown top-level keys"):
        vc_mod.validate_candidate(cand)

    spoofed_versions = {
        **original,
        "versions": {**original["versions"], "vllm": "v9999.0.0"},
    }
    proposal_file.write_text(
        json.dumps(spoofed_versions, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(vc_mod.ValidationError, match="does not match"):
        vc_mod.validate_candidate(cand)


def test_replacing_proposal_file_with_directory_is_rejected(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    proposal_path = cand / ".auto-sync" / "proposal.json"
    proposal_path.unlink()
    proposal_path.mkdir()
    (proposal_path / "nested.json").write_text("{}", encoding="utf-8")

    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)


@pytest.mark.parametrize(
    "mutator, expected_match",
    [
        (
            lambda data: data["spec"]["scope"].__setitem__(
                "writable",
                [".auto-sync/proposal.json", ".AUTO-SYNC", "pack/matrix.yaml"],
            ),
            r"writable path '\.AUTO-SYNC' lives inside protected path '\.auto-sync'",
        ),
        (
            lambda data: data["spec"]["scope"].__setitem__(
                "protected",
                [*data["spec"]["scope"]["protected"], ".AUTO-SYNC/PROPOSAL.JSON"],
            ),
            r"spec\.proposal\.path '\.auto-sync/proposal\.json' overlaps protected path '\.AUTO-SYNC/PROPOSAL\.JSON'",
        ),
        (
            lambda data: data["spec"]["scope"].__setitem__(
                "writable",
                [".auto-sync/proposal.json", ".auto-sync", "pack/matrix.yaml"],
            ),
            r"writable path '\.auto-sync' lives inside protected path '\.auto-sync'",
        ),
        (
            lambda data: data["spec"]["scope"].__setitem__(
                "writable",
                [".auto-sync", "pack/matrix.yaml"],
            ),
            r"control-root spec\.proposal\.path '\.auto-sync/proposal\.json' requires an exact entry",
        ),
        (
            lambda data: data["spec"]["scope"].__setitem__(
                "writable",
                ["pack/matrix.yaml"],
            ),
            r"control-root spec\.proposal\.path '\.auto-sync/proposal\.json' requires an exact entry",
        ),
        (
            lambda data: (
                data["spec"]["proposal"].__setitem__(
                    "path",
                    ".auto-sync/instructions.md",
                ),
                data["spec"]["scope"].__setitem__(
                    "writable",
                    [".auto-sync/instructions.md", "pack/matrix.yaml"],
                ),
            ),
            r"spec\.proposal\.path '\.auto-sync/instructions\.md' overlaps protected path",
        ),
        (
            lambda data: (
                data["spec"]["proposal"].__setitem__(
                    "path",
                    ".auto-sync/memory/proposal.json",
                ),
                data["spec"]["scope"].__setitem__(
                    "writable",
                    [".auto-sync/memory/proposal.json", "pack/matrix.yaml"],
                ),
            ),
            r"spec\.proposal\.path '\.auto-sync/memory/proposal\.json' overlaps protected path",
        ),
    ],
)
def test_invalid_taskpack_control_root_scope_configs_are_rejected(
    baseline_template: Path,
    tmp_path: Path,
    mutator: object,
    expected_match: str,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")
    taskpack_path = cand / ".auto-sync" / "taskpack.yaml"
    manifest = yaml.safe_load(taskpack_path.read_text(encoding="utf-8"))
    assert callable(mutator)
    mutator(manifest)
    taskpack_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(vc_mod.ValidationError, match=expected_match):
        vc_mod.load_effective_scope(cand)


def _sample_memory_entry(
    entry_id: str,
    claim: str = "Verified static checks on main.",
) -> dict[str, object]:
    digest_hex = "a" * 64
    return {
        "version": 1,
        "id": entry_id,
        "claimKey": "check.runner-static-checks",
        "claim": claim,
        "kind": "fact",
        "scope": {
            "taskpack": "auto-sync",
            "repository": "gpustack/runner",
            "paths": [".auto-sync/proposal.json"],
            "targetMatrix": None,
        },
        "sourceRef": {
            "runId": "run-1",
            "lockHash": {"algorithm": "sha256", "hex": digest_hex},
            "candidateDigest": {"algorithm": "sha256", "hex": digest_hex},
        },
        "sourceDigest": {"algorithm": "sha256", "hex": digest_hex},
        "verifiedAtMs": 1000,
        "validFor": {
            "baseRevision": "0" * 40,
            "sourceRevision": "0" * 40,
            "codeFingerprint": {"algorithm": "sha256", "hex": digest_hex},
            "upstreamVersions": {"vllm": "v0.19.0"},
        },
        "expiresAtMs": 2000,
        "supersedes": [],
        "evidenceRefs": [
            {
                "evidenceId": "ev-1",
                "checkId": "runner-static-checks",
                "level": "local_execution",
                "observedStatus": "passed",
                "artifact": {
                    "name": "checks/runner-static-checks.json",
                    "digest": {"algorithm": "sha256", "hex": digest_hex},
                    "byteLength": 128,
                },
            },
        ],
    }


def _write_memory_store(
    cand: Path,
    entry_id: str = "entry.run-1.check.runner-static-checks",
) -> Path:
    digest_hex = "b" * 64
    entry = _sample_memory_entry(entry_id)
    taskpack_dir = cand / ".auto-sync" / "memory" / "auto-sync"
    entries_dir = taskpack_dir / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    index_payload = {
        "version": 1,
        "taskpack": "auto-sync",
        "repository": "gpustack/runner",
        "updatedAtMs": 1000,
        "entries": [entry],
        "retired": [],
        "storeDigest": {"algorithm": "sha256", "hex": digest_hex},
    }
    (taskpack_dir / "index.json").write_text(
        json.dumps(index_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    entry_path = entries_dir / f"{entry_id}.md"
    canonical_header = json.dumps(entry, separators=(",", ":"), sort_keys=True)
    entry_path.write_text(
        f"---\n{canonical_header}\n---\n\n{entry['claim']}\n",
        encoding="utf-8",
    )
    return entry_path


def _commit_all(cand: Path, message: str) -> None:
    git_bin = shutil.which("git")
    assert git_bin is not None
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test Bot",
        "GIT_AUTHOR_EMAIL": "bot@gpustack.ai",
        "GIT_COMMITTER_NAME": "Test Bot",
        "GIT_COMMITTER_EMAIL": "bot@gpustack.ai",
    }
    subprocess.run([git_bin, "add", "-A"], cwd=cand, env=git_env, check=True)
    subprocess.run(
        [git_bin, "commit", "-q", "-m", message],
        cwd=cand,
        env=git_env,
        check=True,
    )


def test_validate_candidate_accepts_committed_memory_store_on_head(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    _write_memory_store(cand)
    _commit_all(cand, "chore(memory): commit auto-sync memory store")
    vc_mod.validate_candidate(cand)


def test_validate_candidate_rejects_candidate_modifying_memory_store(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    _write_memory_store(cand)
    _commit_all(cand, "chore(memory): commit auto-sync memory store")

    evil_entry = cand / ".auto-sync" / "memory" / "auto-sync" / "entries" / "evil.md"
    evil_entry.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)


def test_validate_candidate_rejects_corrupt_or_forbidden_memory_files(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")
    entry_path = _write_memory_store(cand)
    taskpack_dir = cand / ".auto-sync" / "memory" / "auto-sync"

    for bad_name in (".cas.lock", "run.json", "ledger.sqlite", "active-snapshot.md"):
        bad_file = taskpack_dir / bad_name
        bad_file.write_text("bad\n", encoding="utf-8")
        with pytest.raises(vc_mod.ValidationError):
            vc_mod.validate_candidate(cand)
        bad_file.unlink()

    orphan = taskpack_dir / "entries" / "orphan.md"
    orphan.write_text('---\n{"id":"orphan"}\n---\n\norphan\n', encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match=r"do not match index\.json"):
        vc_mod.validate_candidate(cand)
    orphan.unlink()

    original_text = entry_path.read_text(encoding="utf-8")
    entry_path.write_text("missing frontmatter\n", encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match="front-matter"):
        vc_mod.validate_candidate(cand)
    entry_path.write_text(original_text, encoding="utf-8")

    vc_mod.validate_candidate(cand)
