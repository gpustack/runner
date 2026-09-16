"""Behavioral tests for pack/merge_runner.sh.

The script decides what lands in the published `runner.py.json`, and its two
riskiest behaviors are invisible until a release goes wrong: folding a probe
result onto the dependency names, and refusing to invent entries for a post
operation. Both are covered here.

The real script is executed against a sandbox workspace, so nothing in the
repository is written to.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MERGE_RUNNER = REPO_ROOT / "pack" / "merge_runner.sh"
DEPENDENCIES_FILE = REPO_ROOT / "pack" / "dependencies.json"

pytestmark = pytest.mark.skipif(
    shutil.which("yq") is None or shutil.which("jq") is None,
    reason="merge_runner.sh needs yq and jq",
)

MATRIX_YAML = """\
rules:
  - backend: "cuda"
    services:
      - "vllm"
"""

# One build job, shaped like an `expand_matrix.sh` entry. `platform_tag` is the
# key probe results are related back with.
BUILD_JOB = {
    "backend": "cuda",
    "backend_version": "13.0",
    "original_backend_version": "13.0.2",
    "backend_variant": "",
    "service": "vllm",
    "service_version": "0.29.0",
    "platform": "linux/amd64",
    "tag": "cuda13.0-vllm0.29.0",
    "platform_tag": "linux-amd64-cuda13.0-vllm0.29.0",
}

ENTRY = {
    "backend": "cuda",
    "backend_version": "13.0",
    "original_backend_version": "13.0.2",
    "backend_variant": "",
    "service": "vllm",
    "service_version": "0.29.0",
    "platform": "linux/amd64",
    "docker_image": "gpustack/runner:cuda13.0-vllm0.29.0",
    "deprecated": False,
}


def _workspace(tmp_path: Path, entries: list[dict] | None) -> Path:
    """Lay out the directories merge_runner.sh expects, and return the pack dir."""
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "matrix.yaml").write_text(MATRIX_YAML)
    (tmp_path / "gpustack_runner").mkdir()
    (tmp_path / "tests" / "gpustack_runner" / "fixtures").mkdir(parents=True)
    if entries is not None:
        (tmp_path / "gpustack_runner" / "runner.py.json").write_text(
            json.dumps(entries, indent=2),
        )
    return pack


def _probe(tmp_path: Path, platform_tag: str, probed: dict[str, str]) -> Path:
    """Write one downloaded artifact, laid out the way download-artifact does."""
    directory = tmp_path / "dependencies" / f"dependencies-{platform_tag}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dependencies.json").write_text(json.dumps(probed))
    return tmp_path / "dependencies"


def _run(
    pack: Path,
    build_jobs: list[dict],
    dependencies_dir: Path | None = None,
    post_operation: str = "",
) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "INPUT_WORKSPACE": str(pack),
        "INPUT_BUILD_JOBS": json.dumps(build_jobs),
        "INPUT_DEPENDENCIES_FILE": str(DEPENDENCIES_FILE),
        "INPUT_DEPENDENCIES_DIR": str(dependencies_dir) if dependencies_dir else "",
        "INPUT_POST_OPERATION": post_operation,
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(MERGE_RUNNER)],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _merged(pack: Path) -> list[dict]:
    path = pack.parent / "gpustack_runner" / "runner.py.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_probe_result_is_folded_onto_dependency_names(tmp_path):
    """A raw probe result is recorded under dependency names, not distributions."""
    pack = _workspace(tmp_path, [])
    # ``mooncake-transfer-engine-rocm`` outranks the generic build of the same
    # name, which is the whole point of a multi-distribution entry.
    # ``unlisted-package`` is not whitelisted at all and is dropped.
    dependencies_dir = _probe(
        tmp_path,
        BUILD_JOB["platform_tag"],
        {
            "mooncake-transfer-engine": "0.3.13",
            "mooncake-transfer-engine-rocm": "0.3.13.post1",
            "torch": "2.9.0",
            "unlisted-package": "1.0.0",
        },
    )

    result = _run(pack, [BUILD_JOB], dependencies_dir)
    assert result.returncode == 0, result.stderr

    merged = _merged(pack)
    assert len(merged) == 1
    assert merged[0]["dependencies"] == {
        "mooncake-transfer-engine": "0.3.13.post1",
        "torch": "2.9.0",
    }


def test_probed_nothing_installed_stays_an_empty_map(tmp_path):
    """``{}`` means "probed, nothing installed" and must not become absent."""
    pack = _workspace(tmp_path, [])
    dependencies_dir = _probe(tmp_path, BUILD_JOB["platform_tag"], {})

    result = _run(pack, [BUILD_JOB], dependencies_dir)
    assert result.returncode == 0, result.stderr

    merged = _merged(pack)
    assert merged[0]["dependencies"] == {}


def test_unprobed_rebuild_carries_over_existing_dependencies(tmp_path):
    """Rebuilding without a probe must not erase what an earlier build recorded.

    An absent ``dependencies`` means "never probed", so dropping it would be a
    lie that only another rebuild could undo.
    """
    existing = dict(ENTRY, dependencies={"lmcache": "0.5.4"})
    pack = _workspace(tmp_path, [existing])

    result = _run(pack, [BUILD_JOB], dependencies_dir=None)
    assert result.returncode == 0, result.stderr

    merged = _merged(pack)
    assert len(merged) == 1
    assert merged[0]["dependencies"] == {"lmcache": "0.5.4"}


def test_post_operation_updates_in_place_without_adding(tmp_path):
    """A post operation may only refresh ``dependencies`` of existing entries."""
    untouched = dict(
        ENTRY,
        service_version="0.28.0",
        docker_image="gpustack/runner:cuda13.0-vllm0.28.0",
    )
    existing = dict(ENTRY, dependencies={"lmcache": "0.4.3"})
    pack = _workspace(tmp_path, [existing, untouched])
    dependencies_dir = _probe(
        tmp_path,
        BUILD_JOB["platform_tag"],
        {"lmcache": "0.5.4", "torch": "2.9.0"},
    )

    result = _run(pack, [BUILD_JOB], dependencies_dir, post_operation="whatever")
    assert result.returncode == 0, result.stderr

    merged = _merged(pack)
    assert len(merged) == 2, "a post operation must never add or drop an entry"

    by_image = {entry["docker_image"]: entry for entry in merged}
    updated = by_image["gpustack/runner:cuda13.0-vllm0.29.0"]
    assert updated["dependencies"] == {"lmcache": "0.5.4", "torch": "2.9.0"}
    # Every other field of the updated entry, and the other entry as a whole,
    # must come through byte for byte.
    assert {k: v for k, v in updated.items() if k != "dependencies"} == ENTRY
    assert by_image["gpustack/runner:cuda13.0-vllm0.28.0"] == untouched


def test_post_operation_fails_on_a_tag_that_addresses_no_entry(tmp_path):
    """The usual cause is running without ``for_release``, so the tags are dev tags."""
    pack = _workspace(tmp_path, [])
    dependencies_dir = _probe(
        tmp_path,
        BUILD_JOB["platform_tag"],
        {"lmcache": "0.5.4"},
    )

    result = _run(pack, [BUILD_JOB], dependencies_dir, post_operation="whatever")
    assert result.returncode != 0, (
        "expected a post operation addressing no existing entry to fail"
    )
    assert "do not address exactly one existing entry" in result.stderr, result.stderr
