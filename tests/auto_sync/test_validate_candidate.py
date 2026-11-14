"""Tests for .auto-sync/checks/validate_candidate.py and validate_candidate.sh."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKS_DIR = ROOT / ".auto-sync" / "checks"
VALIDATOR_PY = CHECKS_DIR / "validate_candidate.py"
VALIDATOR_SH = CHECKS_DIR / "validate_candidate.sh"
SUBSCRIPTIONS = (
    "cuda/vllm",
    "cuda/sglang",
    "rocm/vllm",
    "rocm/sglang",
    "cann/vllm",
    "cann/sglang",
)


def _unchanged_proposal() -> dict[str, object]:
    return {
        "schema_version": 1,
        "summary": "All subscribed releases match catalog and support records.",
        "subscriptions": {
            sub_id: {
                "status": "unchanged",
                "engine_version": None,
                "plugin_version": None,
                "reason": "Catalog already records the latest eligible release line.",
                "packages": [],
                "patches": [],
                "sources": [],
            }
            for sub_id in SUBSCRIPTIONS
        },
    }


@pytest.fixture
def candidate_dir(tmp_path: Path) -> Path:
    shutil.copy2(ROOT / ".gitignore", tmp_path / ".gitignore")
    shutil.copytree(
        ROOT / "pack",
        tmp_path / "pack",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    (tmp_path / "docs").mkdir()
    shutil.copy2(
        ROOT / "docs" / "support-records.md",
        tmp_path / "docs" / "support-records.md",
    )
    shutil.copy2(
        ROOT / "docs" / "supported-runners.md",
        tmp_path / "docs" / "supported-runners.md",
    )
    shutil.copy2(ROOT / "README.md", tmp_path / "README.md")
    (tmp_path / "gpustack_runner").mkdir()
    shutil.copy2(
        ROOT / "gpustack_runner" / "runner.py.json",
        tmp_path / "gpustack_runner" / "runner.py.json",
    )
    shutil.copytree(ROOT / ".auto-sync", tmp_path / ".auto-sync")
    (tmp_path / ".autosync").mkdir()
    (tmp_path / ".autosync" / "proposal.json").write_text(
        json.dumps(_unchanged_proposal(), indent=2) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_py(
    candidate: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PACK_RUN_URL"}
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(  # noqa: S603 - fixed validator script and temp candidate.
        [sys.executable, str(VALIDATOR_PY), "--candidate-dir", str(candidate)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _run_sh(
    candidate: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **{k: v for k, v in os.environ.items() if k != "PACK_RUN_URL"},
        "LOOPWRIGHT_CANDIDATE_DIR": str(candidate),
        "PYTHON_BIN": sys.executable,
    }
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(  # noqa: S603 - fixed validator wrapper and temp candidate.
        [str(VALIDATOR_SH)],
        cwd=candidate,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _bump_cuda_vllm(candidate: Path, version: str = "0.34.0") -> None:
    df = candidate / "pack" / "cuda" / "Dockerfile.vllm"
    df.write_text(
        df.read_text(encoding="utf-8").replace(
            "ARG VLLM_VERSION=0.33.0",
            f"ARG VLLM_VERSION={version}",
        ),
        encoding="utf-8",
    )
    matrix = candidate / "pack" / "matrix.yaml"
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace(
            '- "VLLM_VERSION=0.33.0"\n      - "VLLM_BASE_IMAGE=vllm/vllm-openai:v0.33.0"',
            f'- "VLLM_VERSION={version}"\n      - "VLLM_BASE_IMAGE=vllm/vllm-openai:v{version}"',
        ),
        encoding="utf-8",
    )


def _init_git_repo(candidate: Path) -> None:
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.name", "Test"],
        ["git", "config", "user.email", "test@gpustack.ai"],
        ["git", "add", "."],
        ["git", "commit", "-m", "init"],
    ):
        res = subprocess.run(  # noqa: S603 - fixed git init steps in temp dir.
            cmd,
            cwd=candidate,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert res.returncode == 0, res.stderr


def test_valid_unchanged_candidate_passes_py_and_sh(candidate_dir: Path) -> None:
    res_py = _run_py(candidate_dir)
    assert res_py.returncode == 0, res_py.stderr
    res_sh = _run_sh(candidate_dir)
    assert res_sh.returncode == 0, res_sh.stderr


def test_valid_ready_proposal_with_prepared_record_and_whitelisted_prerelease(
    candidate_dir: Path,
) -> None:
    _bump_cuda_vllm(candidate_dir, "0.34.0")
    proposal = _unchanged_proposal()
    proposal["versions"] = {"vllm": "v0.34.0", "vllm-ascend": "v0.30.1rc1"}
    subs = proposal["subscriptions"]
    assert isinstance(subs, dict)
    subs["cuda/vllm"] = {
        "status": "ready",
        "engine_version": "0.34.0",
        "plugin_version": None,
        "reason": "Advance cuda/vllm to 0.34.0 with updated LMCache and Omni pins.",
        "packages": [
            {
                "name": "lmcache",
                "version": "0.5.7rc1",
                "decision": "update",
                "reason": "Whitelisted RC required for vLLM 0.34.0.",
                "sources": [
                    "https://github.com/LMCache/LMCache/releases/tag/v0.5.7rc1",
                ],
            },
            {
                "name": "vllm-omni",
                "version": "4b63581cf6527dc5c964558650e996c0a36e027a",
                "decision": "source",
                "reason": "Aligned main commit.",
                "sources": [
                    "https://github.com/vllm-project/vllm-omni/commit/4b63581cf6527dc5c964558650e996c0a36e027a",
                ],
            },
        ],
        "patches": [
            {
                "path": "pack/cuda/patches/vllm/001_wrong_dp_ray.patch",
                "disposition": "retain",
                "reason": "Applies cleanly on 0.34.0.",
                "versions": ["0.34.0"],
                "platforms": ["linux/amd64", "linux/arm64"],
                "sources": [
                    "https://github.com/vllm-project/vllm/releases/tag/v0.34.0",
                ],
            },
        ],
        "sources": ["https://github.com/vllm-project/vllm/releases/tag/v0.34.0"],
    }
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal, indent=2) + "\n",
        encoding="utf-8",
    )

    support_path = candidate_dir / "docs" / "support-records.md"
    support_text = support_path.read_text(encoding="utf-8").replace(
        "<!-- runner-support-records:end -->",
        "| cuda | 13.0 | vllm | - | 0.34.0 | - | linux/amd64, linux/arm64 | prepared |\n<!-- runner-support-records:end -->",
    )
    support_path.write_text(support_text, encoding="utf-8")

    res_py = _run_py(candidate_dir)
    assert res_py.returncode == 0, res_py.stderr
    res_sh = _run_sh(candidate_dir)
    assert res_sh.returncode == 0, res_sh.stderr


def test_valid_patch_deletion_passes(candidate_dir: Path) -> None:
    patch_file = (
        candidate_dir / "pack" / "cuda" / "patches" / "vllm" / "001_wrong_dp_ray.patch"
    )
    patch_file.unlink()
    proposal = _unchanged_proposal()
    subs = proposal["subscriptions"]
    assert isinstance(subs, dict)
    subs["cuda/vllm"]["patches"] = [
        {
            "path": "pack/cuda/patches/vllm/001_wrong_dp_ray.patch",
            "disposition": "remove",
            "reason": "Upstream fixed the Ray DP bug.",
            "versions": ["0.34.0"],
            "platforms": ["linux/amd64", "linux/arm64"],
            "sources": ["https://github.com/vllm-project/vllm/pull/12345"],
        },
    ]
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal, indent=2) + "\n",
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode == 0, res.stderr


def test_rejects_duplicate_json_keys_in_proposal(candidate_dir: Path) -> None:
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        '{"schema_version": 1, "schema_version": 1, "summary": "dup", "subscriptions": {}}\n',
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "duplicate" in res.stderr


def test_rejects_missing_subscription_and_invalid_status(candidate_dir: Path) -> None:
    proposal = _unchanged_proposal()
    subs = copy.deepcopy(proposal["subscriptions"])
    assert isinstance(subs, dict)
    subs.pop("cann/sglang")
    proposal["subscriptions"] = subs
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "subscriptions" in res.stderr

    proposal2 = _unchanged_proposal()
    assert isinstance(proposal2["subscriptions"], dict)
    proposal2["subscriptions"]["cann/sglang"]["status"] = "analyzed"
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal2),
        encoding="utf-8",
    )
    res2 = _run_py(candidate_dir)
    assert res2.returncode != 0
    assert "status" in res2.stderr


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://github.com/vllm-project/vllm",
        "pack/cuda/Dockerfile.vllm",
        "https://example.com/foo",
        "https://sub.example.com/release",
        "https://localhost/vllm",
        "https://github.com/",
    ],
)
def test_rejects_non_https_source_url(candidate_dir: Path, bad_url: str) -> None:
    proposal = _unchanged_proposal()
    assert isinstance(proposal["subscriptions"], dict)
    proposal["subscriptions"]["cuda/vllm"]["sources"] = [bad_url]
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "https" in res.stderr


def test_rejects_unwhitelisted_prerelease_package(candidate_dir: Path) -> None:
    proposal = _unchanged_proposal()
    assert isinstance(proposal["subscriptions"], dict)
    proposal["subscriptions"]["cuda/vllm"]["packages"] = [
        {
            "name": "diffusers",
            "version": "0.33.0rc1",
            "decision": "update",
            "reason": "Try unwhitelisted RC.",
            "sources": ["https://pypi.org/project/diffusers/0.33.0rc1/"],
        },
    ]
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "prereleases.yaml" in res.stderr


@pytest.mark.parametrize("bad_version", ["v0.33.0", "vllm-0.33.0"])
def test_rejects_prefixed_patch_version(candidate_dir: Path, bad_version: str) -> None:
    proposal = _unchanged_proposal()
    assert isinstance(proposal["subscriptions"], dict)
    proposal["subscriptions"]["cuda/vllm"]["patches"] = [
        {
            "path": "pack/cuda/patches/vllm/001_wrong_dp_ray.patch",
            "disposition": "retain",
            "reason": "Retain patch.",
            "versions": [bad_version],
            "platforms": ["linux/amd64"],
            "sources": ["https://github.com/vllm-project/vllm/releases/tag/v0.33.0"],
        },
    ]
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "bare PEP 440" in res.stderr


def test_rejects_duplicate_key_in_matrix_yaml(candidate_dir: Path) -> None:
    matrix_path = candidate_dir / "pack" / "matrix.yaml"
    matrix_path.write_text(
        "rules:\n  - backend: cuda\n    backend: rocm\n    services: [vllm]\n",
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "duplicate" in res.stderr


def test_rejects_lmcache_mismatch_across_cuda_and_rocm(candidate_dir: Path) -> None:
    df = candidate_dir / "pack" / "rocm" / "Dockerfile.sglang"
    df.write_text(
        df.read_text(encoding="utf-8").replace(
            "ARG SGLANG_LMCACHE_VERSION=0.5.6",
            "ARG SGLANG_LMCACHE_VERSION=0.5.7",
        ),
        encoding="utf-8",
    )
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "LMCache" in res.stderr


def test_rejects_missing_referenced_and_orphaned_patch_files(
    candidate_dir: Path,
) -> None:
    cuda_df = candidate_dir / "pack" / "cuda" / "Dockerfile.vllm"
    cuda_df.write_text(
        cuda_df.read_text(encoding="utf-8").replace(
            "/workspace/patches/vllm/*.patch",
            "/workspace/patches/vllm/missing_patch.patch",
        ),
        encoding="utf-8",
    )
    res_missing = _run_py(candidate_dir)
    assert res_missing.returncode != 0
    assert "missing patch" in res_missing.stderr

    orphan_dir = candidate_dir / "pack" / "cuda" / "patches" / "orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "unused.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")
    cuda_df.write_text(
        (ROOT / "pack" / "cuda" / "Dockerfile.vllm").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    res_orphan = _run_py(candidate_dir)
    assert res_orphan.returncode != 0
    assert "unreferenced patch" in res_orphan.stderr


def test_rejects_forged_published_support_row_and_patch_runtime(
    candidate_dir: Path,
) -> None:
    support_path = candidate_dir / "docs" / "support-records.md"
    original = support_path.read_text(encoding="utf-8")

    support_path.write_text(
        original.replace(
            "<!-- runner-support-records:end -->",
            "| cuda | 13.0 | vllm | - | 0.99.0 | - | linux/amd64 | published |\n<!-- runner-support-records:end -->",
        ),
        encoding="utf-8",
    )
    res_forged = _run_py(candidate_dir)
    assert res_forged.returncode != 0
    assert "published" in res_forged.stderr

    support_path.write_text(
        original.replace(
            "<!-- runner-support-records:end -->",
            "| cuda | 13.0.1 | vllm | - | 0.34.0 | - | linux/amd64 | prepared |\n<!-- runner-support-records:end -->",
        ),
        encoding="utf-8",
    )
    res_runtime = _run_py(candidate_dir)
    assert res_runtime.returncode != 0
    assert "major.minor" in res_runtime.stderr


def test_rejects_stray_file_or_subdir_in_autosync_dir(candidate_dir: Path) -> None:
    (candidate_dir / ".autosync" / "notes.txt").write_text("stray", encoding="utf-8")
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "proposal.json" in res.stderr


def test_top_level_versions_validation(candidate_dir: Path) -> None:
    _bump_cuda_vllm(candidate_dir, "0.34.0")
    support_path = candidate_dir / "docs" / "support-records.md"
    support_path.write_text(
        support_path.read_text(encoding="utf-8").replace(
            "<!-- runner-support-records:end -->",
            "| cuda | 13.0 | vllm | - | 0.34.0 | - | linux/amd64, linux/arm64 | prepared |\n<!-- runner-support-records:end -->",
        ),
        encoding="utf-8",
    )

    proposal = _unchanged_proposal()
    assert isinstance(proposal["subscriptions"], dict)
    proposal["subscriptions"]["cuda/vllm"] = {
        "status": "ready",
        "engine_version": "0.34.0",
        "plugin_version": None,
        "reason": "Ready.",
        "packages": [],
        "patches": [],
        "sources": ["https://github.com/vllm-project/vllm/releases/tag/v0.34.0"],
    }

    # Prerelease vllm in versions rejected.
    proposal["versions"] = {"vllm": "0.34.0rc1"}
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res_pre = _run_py(candidate_dir)
    assert res_pre.returncode != 0
    assert "stable" in res_pre.stderr

    # Mismatched vllm version against ready subscription rejected.
    proposal["versions"] = {"vllm": "v0.35.0"}
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res_mismatch = _run_py(candidate_dir)
    assert res_mismatch.returncode != 0
    assert "does not match" in res_mismatch.stderr

    # Unknown upstream key rejected.
    proposal["versions"] = {"mindie": "2.3.0"}
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res_unknown = _run_py(candidate_dir)
    assert res_unknown.returncode != 0
    assert "unknown upstream" in res_unknown.stderr


def test_pack_run_url_validation(candidate_dir: Path) -> None:
    valid_url = (
        "https://github.com/gpustack/runner/actions/runs/123456789/job/987654321"
    )
    res_bad_env = _run_py(
        candidate_dir,
        env_overrides={"PACK_RUN_URL": "https://github.com/other/repo/actions/runs/1"},
    )
    assert res_bad_env.returncode != 0
    assert "PACK_RUN_URL" in res_bad_env.stderr

    res_unreferenced = _run_py(
        candidate_dir,
        env_overrides={"PACK_RUN_URL": valid_url},
    )
    assert res_unreferenced.returncode != 0
    assert "PACK_RUN_URL" in res_unreferenced.stderr

    proposal = _unchanged_proposal()
    proposal["pack_run_url"] = valid_url
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res_ok = _run_py(candidate_dir, env_overrides={"PACK_RUN_URL": valid_url})
    assert res_ok.returncode == 0, res_ok.stderr


def test_ready_subscription_requires_dockerfile_matrix_and_prepared_row(
    candidate_dir: Path,
) -> None:
    proposal = _unchanged_proposal()
    assert isinstance(proposal["subscriptions"], dict)
    proposal["subscriptions"]["cuda/vllm"] = {
        "status": "ready",
        "engine_version": "0.34.0",
        "plugin_version": None,
        "reason": "Ready.",
        "packages": [],
        "patches": [],
        "sources": ["https://github.com/vllm-project/vllm/releases/tag/v0.34.0"],
    }
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )

    # Without Dockerfile bump -> rejected.
    res_no_df = _run_py(candidate_dir)
    assert res_no_df.returncode != 0
    assert "VLLM_VERSION" in res_no_df.stderr

    # Bump Dockerfile only, without matrix.yaml bump -> rejected.
    df = candidate_dir / "pack" / "cuda" / "Dockerfile.vllm"
    df.write_text(
        df.read_text(encoding="utf-8").replace(
            "ARG VLLM_VERSION=0.33.0",
            "ARG VLLM_VERSION=0.34.0",
        ),
        encoding="utf-8",
    )
    res_no_matrix = _run_py(candidate_dir)
    assert res_no_matrix.returncode != 0
    assert "pack/matrix.yaml" in res_no_matrix.stderr

    # Bump matrix.yaml too, without prepared support row -> rejected.
    _bump_cuda_vllm(candidate_dir, "0.34.0")
    res_no_prepared = _run_py(candidate_dir)
    assert res_no_prepared.returncode != 0
    assert "prepared" in res_no_prepared.stderr


def test_ready_cann_vllm_checks_base_image_plugin_version(
    candidate_dir: Path,
) -> None:
    df = candidate_dir / "pack" / "cann" / "Dockerfile.vllm"
    df.write_text(
        df.read_text(encoding="utf-8")
        .replace("ARG VLLM_VERSION=0.30.0", "ARG VLLM_VERSION=0.31.0")
        .replace(
            "ARG CANN_BASE_IMAGE=quay.io/ascend/vllm-ascend:v0.30.0",
            "ARG CANN_BASE_IMAGE=quay.io/ascend/vllm-ascend:v0.31.0rc1",
        ),
        encoding="utf-8",
    )
    matrix = candidate_dir / "pack" / "matrix.yaml"
    matrix.write_text(
        matrix.read_text(encoding="utf-8")
        .replace('- "VLLM_VERSION=0.30.0"', '- "VLLM_VERSION=0.31.0"')
        .replace(
            "quay.io/ascend/vllm-ascend:v0.30.0",
            "quay.io/ascend/vllm-ascend:v0.31.0rc1",
        ),
        encoding="utf-8",
    )
    support_path = candidate_dir / "docs" / "support-records.md"
    support_path.write_text(
        support_path.read_text(encoding="utf-8").replace(
            "<!-- runner-support-records:end -->",
            "| cann | 9.2 | vllm | 910b | 0.31.0 | 0.31.0rc1 | linux/amd64, linux/arm64 | prepared |\n<!-- runner-support-records:end -->",
        ),
        encoding="utf-8",
    )
    proposal = _unchanged_proposal()
    assert isinstance(proposal["subscriptions"], dict)
    proposal["subscriptions"]["cann/vllm"] = {
        "status": "ready",
        "engine_version": "0.31.0",
        "plugin_version": "0.31.0rc1",
        "reason": "Advance cann/vllm.",
        "packages": [],
        "patches": [],
        "sources": [
            "https://github.com/vllm-project/vllm-ascend/releases/tag/v0.31.0rc1",
        ],
    }
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res_ok = _run_py(candidate_dir)
    assert res_ok.returncode == 0, res_ok.stderr

    # Mismatched plugin_version -> rejected.
    proposal["subscriptions"]["cann/vllm"]["plugin_version"] = "0.31.0rc2"
    (candidate_dir / ".autosync" / "proposal.json").write_text(
        json.dumps(proposal),
        encoding="utf-8",
    )
    res_bad = _run_py(candidate_dir)
    assert res_bad.returncode != 0
    assert "plugin_version" in res_bad.stderr


def test_rejects_prerelease_engine_and_unwhitelisted_companion_in_dockerfile(
    candidate_dir: Path,
) -> None:
    df_cuda = candidate_dir / "pack" / "cuda" / "Dockerfile.vllm"
    orig_cuda = df_cuda.read_text(encoding="utf-8")
    df_cuda.write_text(
        orig_cuda.replace("ARG VLLM_VERSION=0.33.0", "ARG VLLM_VERSION=0.34.0rc1"),
        encoding="utf-8",
    )
    res_eng = _run_py(candidate_dir)
    assert res_eng.returncode != 0
    assert "stable" in res_eng.stderr

    df_cuda.write_text(orig_cuda, encoding="utf-8")
    df_rocm = candidate_dir / "pack" / "rocm" / "Dockerfile.vllm"
    df_rocm.write_text(
        df_rocm.read_text(encoding="utf-8").replace(
            "ARG VLLM_MOONCAKE_VERSION=0.3.13.post1",
            "ARG VLLM_MOONCAKE_VERSION=0.4.0rc1",
        ),
        encoding="utf-8",
    )
    res_mooncake = _run_py(candidate_dir)
    assert res_mooncake.returncode != 0
    assert "prereleases.yaml" in res_mooncake.stderr


def test_protects_readme_supported_runners_and_published_rows(
    candidate_dir: Path,
) -> None:
    _init_git_repo(candidate_dir)
    assert _run_py(candidate_dir).returncode == 0

    # Delete a published row in git-tracked support-records.md -> rejected.
    support_path = candidate_dir / "docs" / "support-records.md"
    orig_support = support_path.read_text(encoding="utf-8")
    support_path.write_text(
        orig_support.replace(
            "| cuda | 13.0 | vllm | - | 0.33.0 | - | linux/amd64, linux/arm64 | published |\n",
            "",
        ),
        encoding="utf-8",
    )
    res_deleted_pub = _run_py(candidate_dir)
    assert res_deleted_pub.returncode != 0
    assert "published" in res_deleted_pub.stderr

    # Restore support-records.md, remove README link -> rejected.
    support_path.write_text(orig_support, encoding="utf-8")
    readme_path = candidate_dir / "README.md"
    orig_readme = readme_path.read_text(encoding="utf-8")
    readme_path.write_text("GPUStack Runner\n", encoding="utf-8")
    res_readme = _run_py(candidate_dir)
    assert res_readme.returncode != 0
    assert "docs/supported-runners.md" in res_readme.stderr

    # Restore README, empty supported-runners.md -> rejected.
    readme_path.write_text(orig_readme, encoding="utf-8")
    (candidate_dir / "docs" / "supported-runners.md").write_text("", encoding="utf-8")
    res_sr = _run_py(candidate_dir)
    assert res_sr.returncode != 0
    assert "supported-runners.md" in res_sr.stderr


def test_rejects_broken_matrix_resolution_via_resolve_dockerfile(
    candidate_dir: Path,
) -> None:
    (candidate_dir / "pack" / "corex" / "Dockerfile.vllm").unlink()
    res = _run_py(candidate_dir)
    assert res.returncode != 0
    assert "resolve_dockerfile.sh" in res.stderr


def test_published_row_mutation_rejected_without_git_repo(
    candidate_dir: Path,
) -> None:
    assert not (candidate_dir / ".git").exists()
    assert _run_py(candidate_dir).returncode == 0

    support_path = candidate_dir / "docs" / "support-records.md"
    orig_support = support_path.read_text(encoding="utf-8")
    target_row = "| cuda | 13.0 | vllm | - | 0.33.0 | - | linux/amd64, linux/arm64 | published |\n"
    assert target_row in orig_support

    # Mutating Platforms of an existing published row without .git -> rejected.
    support_path.write_text(
        orig_support.replace(
            target_row,
            "| cuda | 13.0 | vllm | - | 0.33.0 | - | linux/amd64 | published |\n",
        ),
        encoding="utf-8",
    )
    res_platforms = _run_py(candidate_dir)
    assert res_platforms.returncode != 0
    assert "platforms" in res_platforms.stderr

    # Mutating Runtime of an existing published row without .git -> rejected.
    support_path.write_text(
        orig_support.replace(
            target_row,
            "| cuda | 12.9 | vllm | - | 0.33.0 | - | linux/amd64, linux/arm64 | published |\n",
        ),
        encoding="utf-8",
    )
    res_runtime = _run_py(candidate_dir)
    assert res_runtime.returncode != 0
    assert "published" in res_runtime.stderr

    # Deleting an existing latest published row without .git -> rejected.
    support_path.write_text(
        orig_support.replace(target_row, ""),
        encoding="utf-8",
    )
    res_deleted = _run_py(candidate_dir)
    assert res_deleted.returncode != 0
    assert "published" in res_deleted.stderr


def test_enforces_protected_wins_over_writable_scope(candidate_dir: Path) -> None:
    # Stray non-protected file inside writable pack/cuda is rejected even without .git.
    stray = candidate_dir / "pack" / "cuda" / "Dockerfile.extra"
    stray.write_text("FROM scratch\n", encoding="utf-8")
    res_stray = _run_py(candidate_dir)
    assert res_stray.returncode != 0
    assert "pack/cuda/Dockerfile.extra" in res_stray.stderr
    stray.unlink()

    _init_git_repo(candidate_dir)

    # Writable synced recipe inside pack/cuda passes.
    vllm_df = candidate_dir / "pack" / "cuda" / "Dockerfile.vllm"
    orig_vllm_df = vllm_df.read_text(encoding="utf-8")
    vllm_df.write_text(
        orig_vllm_df + "# Benign comment inside writable recipe.\n",
        encoding="utf-8",
    )
    res_writable = _run_py(candidate_dir)
    assert res_writable.returncode == 0, res_writable.stderr
    vllm_df.write_text(orig_vllm_df, encoding="utf-8")

    # Protected carve-outs inside pack/cuda and pack/cann are rejected (protected wins over writable).
    for protected_rel in (
        "pack/cuda/Dockerfile.voxbox",
        "pack/cann/Dockerfile.mindie",
        "pack/cann/patches/hixl/001_channel_generation.patch",
    ):
        target = candidate_dir / protected_rel
        orig_bytes = target.read_bytes()
        target.write_bytes(orig_bytes + b"\n# unauthorized edit\n")
        res_prot = _run_py(candidate_dir)
        assert res_prot.returncode != 0
        assert "protected" in res_prot.stderr
        assert protected_rel in res_prot.stderr
        target.write_bytes(orig_bytes)

    # Paths outside writable scope are rejected.
    for outside_rel in (
        "gpustack_runner/runner.py.json",
        "pack/dependencies.json",
    ):
        target = candidate_dir / outside_rel
        orig_bytes = target.read_bytes()
        target.write_bytes(orig_bytes + b"\n")
        res_outside = _run_py(candidate_dir)
        assert res_outside.returncode != 0
        assert "outside writable scope" in res_outside.stderr
        assert outside_rel in res_outside.stderr
        target.write_bytes(orig_bytes)
