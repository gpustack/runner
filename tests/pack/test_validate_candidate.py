"""Behavior tests for .auto-sync/checks/validate_candidate.py and workflow linting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Subprocess calls invoke fixed git and bash binaries on temporary candidate directories.
# ruff: noqa: S603

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / ".auto-sync" / "checks" / "validate_candidate.py"
LINT_WORKFLOWS_PATH = REPO_ROOT / ".auto-sync" / "checks" / "lint_workflows.py"
SCRIPT_PATH = REPO_ROOT / ".auto-sync" / "checks" / "validate_candidate.sh"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    prev_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prev_dont_write_bytecode
    return module


vc_mod = _load_module("validate_candidate", MODULE_PATH)
lint_workflows = _load_module("lint_workflows", LINT_WORKFLOWS_PATH)

CANDIDATE_COPY_PATHS = (
    ".auto-sync",
    "README.md",
    "docs",
    "gpustack_runner",
    "pack",
)
LARGE_FIXTURE_THRESHOLD_BYTES = 1_048_576


def _copy_fixture_file(src: str, dst: str) -> str:
    src_path = Path(src)
    dst_path = Path(dst)
    if src_path.stat().st_size > LARGE_FIXTURE_THRESHOLD_BYTES:
        dst_path.write_bytes(b"placeholder\n")
        return dst
    return shutil.copy2(src, dst)


def _ignore_copy(_src: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".DS_Store"}}


def _build_candidate_workspace(tmp_path: Path, *, with_git: bool = True) -> Path:
    cand = tmp_path / "candidate"
    cand.mkdir()
    for rel in CANDIDATE_COPY_PATHS:
        src = REPO_ROOT / rel
        dst = cand / rel
        if src.is_dir():
            shutil.copytree(
                src,
                dst,
                symlinks=False,
                ignore=_ignore_copy,
                copy_function=_copy_fixture_file,
            )
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy_fixture_file(str(src), str(dst))

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
        subprocess.run([git_bin, "init", "-q"], cwd=cand, env=git_env, check=True)
        subprocess.run([git_bin, "add", "-A"], cwd=cand, env=git_env, check=True)
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


def _compute_lock_entry_sha256(root: Path, rel_path: str, kind: str) -> str:
    target = root / rel_path
    if kind == "file":
        return hashlib.sha256(target.read_bytes()).hexdigest()
    assert kind == "directory"
    files: list[tuple[str, int, str]] = []
    for item in sorted(target.rglob("*")):
        if item.name in {"__pycache__", ".DS_Store"} or "__pycache__" in item.parts:
            continue
        if item.is_file():
            data = item.read_bytes()
            rel_child = item.relative_to(target).as_posix()
            files.append((rel_child, len(data), hashlib.sha256(data).hexdigest()))
    files.sort(key=lambda entry: entry[0])
    tree_hash = hashlib.sha256(b"loopwright.dev/digests/tree/v1\n")
    for rel_child, byte_len, digest_hex in files:
        tree_hash.update(f"{rel_child}\0{byte_len}\0{digest_hex}\n".encode())
    return tree_hash.hexdigest()


def test_instructions_size_budget_and_auto_sync_workflow_pass_lint(
    tmp_path: Path,
) -> None:
    instructions_bytes = (REPO_ROOT / ".auto-sync" / "instructions.md").read_bytes()
    assert len(instructions_bytes) <= 24576
    assert (
        lint_workflows.main(
            [str(REPO_ROOT / ".github" / "workflows" / "auto-sync.yml")],
        )
        == 0
    )

    taskpack = yaml.safe_load(
        (REPO_ROOT / ".auto-sync" / "taskpack.yaml").read_text(encoding="utf-8"),
    )
    assert taskpack["spec"]["baselineAlignment"] == {"policy": "extract-context"}

    memory_index = REPO_ROOT / ".auto-sync" / "memory" / "auto-sync" / "index.json"
    assert memory_index.read_bytes().endswith(b"\n")

    pre_commit = yaml.safe_load(
        (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"),
    )
    eof_hooks = [
        hook
        for repo in pre_commit["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == "end-of-file-fixer"
    ]
    assert len(eof_hooks) == 1
    assert eof_hooks[0].get("exclude") == r"\.patch$"

    lock_data = json.loads(
        (REPO_ROOT / ".auto-sync" / "digests.lock.json").read_text(encoding="utf-8"),
    )
    for entry in lock_data["entries"]:
        actual = _compute_lock_entry_sha256(REPO_ROOT, entry["path"], entry["kind"])
        assert actual == entry["sha256"], f"stale digest lock entry for {entry['path']}"

    drifted_root = tmp_path / "drifted"
    shutil.copytree(
        REPO_ROOT / ".auto-sync" / "checks",
        drifted_root / ".auto-sync" / "checks",
        ignore=_ignore_copy,
    )
    (drifted_root / ".auto-sync" / "checks" / "validate_candidate.sh").write_text(
        "#!/usr/bin/env bash\nexit 1\n",
        encoding="utf-8",
    )
    checks_expected = next(
        e["sha256"] for e in lock_data["entries"] if e["path"] == ".auto-sync/checks"
    )
    assert (
        _compute_lock_entry_sha256(drifted_root, ".auto-sync/checks", "directory")
        != checks_expected
    )


def test_baseline_and_shell_entrypoint_ignore_poisoned_candidate_script(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    assert not (cand / ".claude").exists()
    vc_mod.validate_candidate(cand)

    shutil.rmtree(cand / ".git")
    poisoned = cand / ".auto-sync" / "checks" / "validate_candidate.py"
    poisoned.write_text("import sys; sys.exit(99)\n", encoding="utf-8")

    pycache_dir = REPO_ROOT / ".auto-sync" / "checks" / "__pycache__"
    if pycache_dir.exists():
        shutil.rmtree(pycache_dir)

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
    assert not pycache_dir.exists()


def test_classify_scope_path_defaults_fail_closed_and_protects_tool_paths(
    baseline_template: Path,
) -> None:
    writable, protected, manifest_protected = vc_mod.load_effective_scope(
        baseline_template,
    )
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
    assert (
        vc_mod.classify_scope_path("pack/cuda/Dockerfile.vllm", writable, protected)
        == "writable"
    )
    assert (
        vc_mod.classify_scope_path("pack/cuda/Dockerfile.voxbox", writable, protected)
        == "protected"
    )
    assert (
        vc_mod.classify_scope_path(
            "pack/cann/patches/hixl/001_fix.patch",
            writable,
            protected,
        )
        == "protected"
    )
    # Explicit manifest protection must cover tracked tool paths without relying on engine defaults.
    assert (
        vc_mod.classify_scope_path(".claude/skills", writable, manifest_protected)
        == "protected"
    )
    assert (
        vc_mod.classify_scope_path("AGENTS.md", writable, manifest_protected)
        == "protected"
    )


def test_git_scope_allows_proposal_edit_and_rejects_protected_edits(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)

    proposal_file = cand / ".auto-sync" / "proposal.json"
    orig_proposal = proposal_file.read_text(encoding="utf-8")
    payload = json.loads(orig_proposal)
    payload["summary"] = "Updated proposal summary inside .auto-sync/proposal.json."
    proposal_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    vc_mod.validate_candidate(cand)
    proposal_file.write_text(orig_proposal, encoding="utf-8")

    for protected_rel in (
        ".auto-sync/instructions.md",
        ".auto-sync/taskpack.yaml",
        ".auto-sync/digests.lock.json",
        ".auto-sync/checks/validate_candidate.sh",
        ".auto-sync/memory/.gitkeep",
    ):
        target = cand / protected_rel
        orig_text = target.read_text(encoding="utf-8")
        target.write_text(orig_text + "\n# unauthorized edit\n", encoding="utf-8")
        with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
            vc_mod.validate_candidate(cand)
        target.write_text(orig_text, encoding="utf-8")

    claude_dir = cand / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)
    shutil.rmtree(claude_dir)

    agents_file = cand / "AGENTS.md"
    agents_file.write_text("# unauthorized\n", encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)
    agents_file.unlink()

    proposal_file.unlink()
    proposal_file.mkdir()
    (proposal_file / "nested.json").write_text("{}", encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)


def test_control_root_rejects_unexpected_entries_symlinks_and_hardlinks(
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

    raw_subs = original.get("subscriptions")
    sub_items = (
        list(raw_subs.items())
        if isinstance(raw_subs, dict)
        else [(item["subscription"], item) for item in raw_subs]
    )
    spoof_upstream = "vllm"
    for sub_id, entry in sub_items:
        if entry.get("status") not in {"ready", "unchanged"}:
            continue
        target_ver = (
            entry.get("plugin_version")
            if sub_id == "cann/vllm"
            else entry.get("engine_version")
        )
        if target_ver is not None:
            spoof_upstream = (
                "vllm-ascend" if sub_id == "cann/vllm" else sub_id.split("/", 1)[1]
            )
            break

    spoofed_versions = {
        **original,
        "versions": {**(original.get("versions") or {}), spoof_upstream: "v9999.0.0"},
    }
    proposal_file.write_text(
        json.dumps(spoofed_versions, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(vc_mod.ValidationError, match="does not match"):
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
            lambda data: data["spec"]["scope"].__setitem__(
                "writable",
                [".auto-sync/proposal.json", "pack/cuda"],
            ),
            r"directory writable path 'pack/cuda' must use explicit 'pack/cuda/\*\*'",
        ),
        (
            lambda data: data["spec"]["scope"].__setitem__(
                "protected",
                ["pack/cann/patches/hixl"],
            ),
            r"directory protected path 'pack/cann/patches/hixl' must use explicit 'pack/cann/patches/hixl/\*\*'",
        ),
    ],
)
def test_invalid_taskpack_scope_configs_are_rejected(
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


def test_bare_outside_writable_dir_and_missing_writable_protected_file_are_rejected(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")
    taskpack_path = cand / ".auto-sync" / "taskpack.yaml"
    manifest = yaml.safe_load(taskpack_path.read_text(encoding="utf-8"))

    (cand / ".claude").mkdir()
    manifest["spec"]["scope"]["protected"] = [".claude"]
    taskpack_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(
        vc_mod.ValidationError,
        match=r"directory protected path '\.claude' must use explicit '\.claude/\*\*'",
    ):
        vc_mod.load_effective_scope(cand)

    manifest["spec"]["scope"]["protected"] = [
        ".claude/**",
        "pack/cuda/Dockerfile.voxbox",
    ]
    taskpack_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    (cand / "pack" / "cuda" / "Dockerfile.voxbox").unlink()
    with pytest.raises(
        vc_mod.ValidationError,
        match=r"protected path missing from candidate: pack/cuda/Dockerfile\.voxbox",
    ):
        vc_mod.load_effective_scope(cand)


def test_memory_store_validation_accepts_valid_and_rejects_corrupt_or_forbidden_files(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")
    entry_id = "entry.run-1.check.runner-static-checks"
    digest_hex = "a" * 64
    entry = {"id": entry_id, "claim": "Verified static checks on main."}
    taskpack_dir = cand / ".auto-sync" / "memory" / "auto-sync"
    if taskpack_dir.exists():
        shutil.rmtree(taskpack_dir)
    entries_dir = taskpack_dir / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    index_payload = {
        "version": 1,
        "taskpack": "auto-sync",
        "repository": "gpustack/runner",
        "entries": [entry],
        "retired": [],
        "storeDigest": {"algorithm": "sha256", "hex": digest_hex},
    }
    (taskpack_dir / "index.json").write_text(
        json.dumps(index_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    entry_path = entries_dir / f"{entry_id}.md"
    entry_text = f"---\n{json.dumps(entry, sort_keys=True)}\n---\n\nVerified.\n"
    entry_path.write_text(entry_text, encoding="utf-8")
    vc_mod.validate_candidate(cand)

    for bad_name in (".cas.lock", "run.json", "ledger.sqlite", "active-snapshot.md"):
        bad_file = taskpack_dir / bad_name
        bad_file.write_text("bad\n", encoding="utf-8")
        with pytest.raises(vc_mod.ValidationError):
            vc_mod.validate_candidate(cand)
        bad_file.unlink()

    orphan = entries_dir / "orphan.md"
    orphan.write_text('---\n{"id":"orphan"}\n---\n\norphan\n', encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match=r"do not match index\.json"):
        vc_mod.validate_candidate(cand)
    orphan.unlink()

    entry_path.write_text("missing frontmatter\n", encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match="front-matter"):
        vc_mod.validate_candidate(cand)
    entry_path.write_text(entry_text, encoding="utf-8")
    vc_mod.validate_candidate(cand)


def test_loopwright_base_dir_enforces_scope_and_published_rows_without_git(
    baseline_template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_snap = tmp_path / "base"
    shutil.copytree(baseline_template, base_snap, symlinks=True)
    shutil.rmtree(base_snap / ".git")

    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")
    monkeypatch.setenv("LOOPWRIGHT_BASE_DIR", str(base_snap))
    vc_mod.validate_candidate(cand)

    voxbox = cand / "pack" / "cuda" / "Dockerfile.voxbox"
    orig_voxbox = voxbox.read_text(encoding="utf-8")
    same_len_voxbox = ("#" if orig_voxbox[0] != "#" else " ") + orig_voxbox[1:]
    voxbox.write_text(same_len_voxbox, encoding="utf-8")
    with pytest.raises(vc_mod.ValidationError, match="modified path is protected"):
        vc_mod.validate_candidate(cand)
    voxbox.write_text(orig_voxbox, encoding="utf-8")

    support_records = cand / "docs" / "support-records.md"
    lines = support_records.read_text(encoding="utf-8").splitlines()
    first_pub = next(r for r in lines if "| published |" in r)
    dropped = [line for line in lines if line != first_pub]
    support_records.write_text("\n".join(dropped) + "\n", encoding="utf-8")
    with pytest.raises(
        vc_mod.ValidationError,
        match="deleted or altered existing published row",
    ):
        vc_mod.validate_candidate(cand)


def test_ready_subscription_allows_published_record_and_rejects_missing_prepared(
    baseline_template: Path,
    tmp_path: Path,
) -> None:
    cand = _clone_candidate(baseline_template, tmp_path)
    shutil.rmtree(cand / ".git")

    # Baseline on main may carry ready subscriptions already promoted to published.
    vc_mod.validate_candidate(cand)

    # Removing the support row while keeping the published catalog entry should
    # report that either 'prepared' or 'published' is required.
    support_records = cand / "docs" / "support-records.md"
    lines = support_records.read_text(encoding="utf-8").splitlines()
    filtered = [
        line
        for line in lines
        if not ("| cuda |" in line and "| vllm |" in line and "| 0.34.0 |" in line)
    ]
    support_records.write_text("\n".join(filtered) + "\n", encoding="utf-8")

    with pytest.raises(
        vc_mod.ValidationError,
        match=r"ready subscription cuda/vllm 0\.34\.0 requires at least one 'prepared' or 'published' row in docs/support-records\.md",
    ):
        vc_mod.validate_candidate(cand)

    # Removing the catalog entry as well must still fail the missing-'prepared' gate.
    catalog_path = cand / "gpustack_runner" / "runner.py.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog = [
        item
        for item in catalog
        if not (
            item.get("backend") == "cuda"
            and item.get("service") == "vllm"
            and item.get("service_version") == "0.34.0"
        )
    ]
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(
        vc_mod.ValidationError,
        match=r"ready subscription cuda/vllm 0\.34\.0 requires at least one 'prepared' row in docs/support-records\.md",
    ):
        vc_mod.validate_candidate(cand)
