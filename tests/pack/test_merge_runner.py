"""Behavioral tests for pack/merge_runner.sh.

The script decides what lands in the published `runner.py.json`, and its two
riskiest behaviors are invisible until a release goes wrong: folding a probe
result onto the dependency names, and refusing to invent entries for a post
operation. Both are covered here.

The real script is executed against a sandbox workspace, so nothing in the
repository is written to.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
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


def _digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
        ).hexdigest()
    )


def _publication(tmp_path, jobs, probed=None, *, unknown=False):
    matrix = {
        "repository": "gpustack/runner",
        "build_jobs": jobs,
        "manifest_jobs": {},
    }
    for job in jobs:
        matrix["manifest_jobs"].setdefault(job["tag"], []).append(job["platform_tag"])
    invocation = {
        "workflow_run": "123",
        "source_revision": "b" * 40,
        "matrix_digest": _digest(matrix),
        "mapping_digest": _digest(json.loads(DEPENDENCIES_FILE.read_text())),
    }
    context = {"invocation": invocation, "matrix": matrix}
    artifacts = tmp_path / "artifacts"
    registry = {}
    for index, job in enumerate(jobs):
        build = {
            "job": job["platform_tag"],
            "attempt": 1,
            "backend": job["backend"],
            "service": job["service"],
            "image": f"gpustack/runner:{job['platform_tag']}",
            "platform": job["platform"],
            "image_digest": "sha256:" + str(index + 1) * 64,
        }
        record = {"invocation": invocation, "build": build}
        receipt = {
            **record,
            "schema_version": 1,
            "status": "unknown" if unknown else "succeeded",
        }
        if not unknown:
            receipt.update(
                distributions=(probed or {}).get(job["platform_tag"], {}),
                interpreter="/opt/venv/bin/python",
                prefix="/opt/venv",
            )
        for prefix, name, value in (
            ("builds", "build.json", record),
            ("dependencies", "receipt.json", receipt),
        ):
            directory = artifacts / f"{prefix}-{job['platform_tag']}"
            directory.mkdir(parents=True)
            (directory / name).write_text(json.dumps(value))
        manifest = registry.setdefault(
            "gpustack/runner:" + job["tag"],
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [],
            },
        )
        manifest["manifests"].append(
            {
                "digest": build["image_digest"],
                "platform": {
                    "os": "linux",
                    "architecture": job["platform"].split("/")[1],
                },
            },
        )
    published = {
        "invocation": invocation,
        "manifests": {
            tag: "sha256:"
            + hashlib.sha256(
                json.dumps(registry["gpustack/runner:" + tag]).encode(),
            ).hexdigest()
            for tag in matrix["manifest_jobs"]
        },
    }
    (tmp_path / "context.json").write_text(json.dumps(context))
    (tmp_path / "manifests.json").write_text(json.dumps(published))
    (tmp_path / "registry.json").write_text(json.dumps(registry))
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "assert sys.argv[1:5] == ['buildx', 'imagetools', 'inspect', '--raw']\n"
        "with open(os.environ['FAKE_REGISTRY']) as source: registry = json.load(source)\n"
        "sys.stdout.write(json.dumps(registry[sys.argv[5]]))\n",
    )
    docker.chmod(0o755)
    return artifacts


def _probe(tmp_path, platform_tag, probed):
    return _publication(tmp_path, [BUILD_JOB], {platform_tag: probed})


def _run(
    pack,
    build_jobs,
    dependencies_dir=None,
    post_operation="",
    *,
    allow_unknown=False,
):
    env = {
        "PATH": f"{pack.parent / 'bin'}:{Path(sys.executable).parent}:{os.environ['PATH']}",
        "INPUT_WORKSPACE": str(pack),
        "INPUT_BUILD_JOBS": json.dumps(build_jobs),
        "INPUT_CONTEXT": (pack.parent / "context.json").read_text()
        if (pack.parent / "context.json").exists()
        else "",
        "INPUT_DEPENDENCIES_FILE": str(DEPENDENCIES_FILE),
        "INPUT_DEPENDENCIES_DIR": str(dependencies_dir) if dependencies_dir else "",
        "INPUT_MANIFESTS_FILE": str(pack.parent / "manifests.json"),
        "INPUT_POST_OPERATION": post_operation,
        "INPUT_ALLOW_UNKNOWN": "true" if allow_unknown else "false",
        "FAKE_REGISTRY": str(pack.parent / "registry.json"),
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(MERGE_RUNNER)],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def _merged(pack: Path) -> list[dict]:
    path = pack.parent / "gpustack_runner" / "runner.py.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _maintenance_workspace(tmp_path, entries):
    pack = _workspace(tmp_path, entries)
    for name in ("merge_runner.sh", "prune_runner.sh", "discard_runner.sh"):
        shutil.copy2(REPO_ROOT / "pack" / name, pack / name)
    fixture_path = (
        tmp_path
        / "tests"
        / "gpustack_runner"
        / "fixtures"
        / "test_list_runners_by_backend.json"
    )
    fixture_path.write_text(json.dumps([["cuda", {"backend": "cuda"}, entries]]))
    # No collector, mapping, receipts, or registry are available in this workspace.
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf "unexpected registry access\\n" >&2\n'
        'touch "$DOCKER_CALL_LOG"\nexit 1\n',
    )
    docker.chmod(0o755)
    return pack, fixture_path


def _run_maintenance(pack, script, **inputs):
    return subprocess.run(  # noqa: S603
        ["bash", str(pack / script)],  # noqa: S607
        env={
            "PATH": f"{pack.parent / 'bin'}:{os.environ['PATH']}",
            "INPUT_WORKSPACE": str(pack),
            "INPUT_TEMPDIR": str(pack.parent),
            "DOCKER_CALL_LOG": str(pack.parent / "docker-called"),
            **inputs,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


@pytest.mark.parametrize("operation", ["prune", "discard"])
@pytest.mark.parametrize("dependencies", [None, {}, {"torch": "2.9.0rc1+local"}])
def test_catalog_only_callers_refresh_fixtures(tmp_path, operation, dependencies):
    selected = dict(ENTRY, custom={"note": "preserved", "enabled": True})
    if dependencies is not None:
        selected["dependencies"] = dependencies
    untouched = dict(
        selected,
        backend_version="12.8",
        original_backend_version="12.8.1",
        docker_image="gpustack/runner:cuda12.8-vllm0.29.0",
    )
    pack, fixture_path = _maintenance_workspace(tmp_path, [selected, untouched])

    result = _run_maintenance(
        pack,
        f"{operation}_runner.sh",
        INPUT_BACKEND="cuda",
        INPUT_BACKEND_VERSION="13.0",
    )

    assert result.returncode == 0, result.stderr
    expected = (
        [untouched]
        if operation == "prune"
        else [dict(selected, deprecated=True), untouched]
    )
    assert _merged(pack) == expected
    assert json.loads(fixture_path.read_text()) == [
        ["cuda", {"backend": "cuda"}, expected],
    ]
    assert not (tmp_path / "docker-called").exists()


def test_explicit_catalog_refresh_preserves_existing_rows(tmp_path):
    entries = [dict(ENTRY, dependencies={"torch": "2.9.0+local"}, custom=["preserved"])]
    pack, fixture_path = _maintenance_workspace(tmp_path, entries)
    fixture_path.write_text("[]")

    result = _run_maintenance(pack, "merge_runner.sh", INPUT_CATALOG_REFRESH="true")

    assert result.returncode == 0, result.stderr
    assert _merged(pack) == entries
    assert json.loads(fixture_path.read_text()) == [
        ["cuda", {"backend": "cuda"}, entries],
    ]
    assert not (tmp_path / "docker-called").exists()


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"INPUT_CONTEXT": ""},
        {"INPUT_CONTEXT": "{invalid"},
        {"INPUT_CONTEXT": "{}"},
    ],
)
def test_pack_without_valid_context_never_refreshes_catalog(tmp_path, inputs):
    pack, fixture_path = _maintenance_workspace(tmp_path, [ENTRY])
    catalog_path = tmp_path / "gpustack_runner" / "runner.py.json"
    before = [path.read_bytes() for path in (catalog_path, fixture_path)]

    result = _run_maintenance(
        pack,
        "merge_runner.sh",
        INPUT_DEPENDENCIES_DIR=str(tmp_path),
        INPUT_MANIFESTS_FILE=str(tmp_path / "manifests.json"),
        **inputs,
    )

    assert result.returncode != 0
    assert [path.read_bytes() for path in (catalog_path, fixture_path)] == before
    assert not (tmp_path / "docker-called").exists()


@pytest.mark.parametrize(
    "name, value",
    [
        ("INPUT_CONTEXT", "{}"),
        ("INPUT_BUILD_JOBS", "[]"),
        ("INPUT_DEPENDENCIES_DIR", "artifacts"),
        ("INPUT_DEPENDENCIES_FILE", "mapping.json"),
        ("INPUT_MANIFESTS_FILE", "manifests.json"),
        ("INPUT_POST_OPERATION", "repair"),
        ("INPUT_ALLOW_UNKNOWN", "true"),
    ],
)
def test_catalog_refresh_rejects_build_inputs(tmp_path, name, value):
    pack, fixture_path = _maintenance_workspace(tmp_path, [ENTRY])
    catalog_path = tmp_path / "gpustack_runner" / "runner.py.json"
    before = [path.read_bytes() for path in (catalog_path, fixture_path)]

    result = _run_maintenance(
        pack,
        "merge_runner.sh",
        INPUT_CATALOG_REFRESH="true",
        **{name: value},
    )

    assert result.returncode != 0
    assert "Catalog refresh cannot use" in result.stderr
    assert name in result.stderr
    assert [path.read_bytes() for path in (catalog_path, fixture_path)] == before
    assert not (tmp_path / "docker-called").exists()


def test_probe_result_is_folded_onto_dependency_names(tmp_path):
    """A raw probe result is recorded under dependency names, not distributions."""
    pack = _workspace(tmp_path, [])
    # ``mooncake-transfer-engine-rocm`` outranks the generic build of the same
    # name, which is the whole point of a multi-distribution entry.
    dependencies_dir = _probe(
        tmp_path,
        BUILD_JOB["platform_tag"],
        {
            "mooncake-transfer-engine": "0.3.13",
            "mooncake-transfer-engine-rocm": "0.3.13.post1",
            "torch": "2.9.0",
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


def test_unprobed_rebuild_fails_without_changing_catalog(tmp_path):
    existing = dict(ENTRY, dependencies={"lmcache": "0.5.4"})
    pack = _workspace(tmp_path, [existing])
    before = (pack.parent / "gpustack_runner" / "runner.py.json").read_bytes()
    result = _run(pack, [BUILD_JOB])
    assert result.returncode != 0
    assert (pack.parent / "gpustack_runner" / "runner.py.json").read_bytes() == before


@pytest.mark.parametrize("operation", ["", "repair"])
def test_disabled_collection_removes_old_dependencies(tmp_path, operation):
    pack = _workspace(tmp_path, [dict(ENTRY, dependencies={"lmcache": "0.5.4"})])
    artifacts = _publication(tmp_path, [BUILD_JOB], unknown=True)
    result = _run(pack, [BUILD_JOB], artifacts, operation, allow_unknown=True)
    assert result.returncode == 0, result.stderr
    assert _merged(pack) == [ENTRY]


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


@pytest.mark.parametrize("count", [0, 2])
def test_post_operation_requires_exactly_one_existing_row(tmp_path, count):
    pack = _workspace(tmp_path, [ENTRY] * count)
    artifacts = _probe(tmp_path, BUILD_JOB["platform_tag"], {"torch": "2.9.0"})
    before = (pack.parent / "gpustack_runner" / "runner.py.json").read_bytes()
    result = _run(pack, [BUILD_JOB], artifacts, "repair")
    assert result.returncode != 0
    assert "exactly one existing entry" in result.stderr
    assert (pack.parent / "gpustack_runner" / "runner.py.json").read_bytes() == before


def test_each_platform_has_its_own_dependencies_and_untouched_rows_survive(tmp_path):
    other = dict(ENTRY, docker_image="gpustack/runner:older", custom="preserved")
    pack = _workspace(tmp_path, [dict(ENTRY, dependencies={"torch": "old"}), other])
    arm = dict(
        BUILD_JOB,
        platform="linux/arm64",
        platform_tag=BUILD_JOB["platform_tag"].replace("amd64", "arm64"),
    )
    artifacts = _publication(
        tmp_path,
        [BUILD_JOB, arm],
        {
            BUILD_JOB["platform_tag"]: {"torch": "2.9.0+amd64"},
            arm["platform_tag"]: {"torch": "2.9.0rc1+arm64", "lmcache": "0.5.4"},
        },
    )
    result = _run(pack, [BUILD_JOB, arm], artifacts)
    assert result.returncode == 0, result.stderr
    merged = _merged(pack)
    assert other in merged
    changed = {
        row["platform"]: row["dependencies"]
        for row in merged
        if row["docker_image"] == ENTRY["docker_image"]
    }
    assert changed == {
        "linux/amd64": {"torch": "2.9.0+amd64"},
        "linux/arm64": {"torch": "2.9.0rc1+arm64", "lmcache": "0.5.4"},
    }


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "failed",
        "digest",
        "source",
        "mapping",
        "platform",
        "malformed",
        "extra",
        "manifest",
        "tag",
        "fixture",
    ],
)
def test_invalid_publication_leaves_catalog_and_fixtures_unchanged(tmp_path, failure):
    pack = _workspace(tmp_path, [dict(ENTRY, dependencies={"torch": "old"})])
    artifacts = _probe(tmp_path, BUILD_JOB["platform_tag"], {"torch": "2.9.0"})
    receipt_path = next(artifacts.glob("dependencies-*/receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    if failure == "missing":
        receipt_path.unlink()
    elif failure == "malformed":
        receipt_path.write_text("{invalid")
    elif failure == "extra":
        shutil.copytree(receipt_path.parent, artifacts / "dependencies-unexpected")
    elif failure == "fixture":
        (pack / "matrix.yaml").write_text("rules: [broken")
    elif failure in {"manifest", "tag"}:
        path = tmp_path / "registry.json"
        registry = json.loads(path.read_text())
        manifest = registry[ENTRY["docker_image"]]
        if failure == "manifest":
            manifest["manifests"][0]["digest"] = "sha256:" + "f" * 64
        else:
            manifest["annotations"] = {"changed": "external-writer"}
        path.write_text(json.dumps(registry))
    else:
        if failure == "failed":
            receipt["status"] = "failed"
        elif failure == "digest":
            receipt["build"]["image_digest"] = "sha256:" + "f" * 64
        elif failure == "platform":
            receipt["build"]["platform"] = "linux/arm64"
        elif failure == "source":
            receipt["invocation"]["source_revision"] = "c" * 40
        else:
            receipt["invocation"]["mapping_digest"] = "sha256:" + "c" * 64
        receipt_path.write_text(json.dumps(receipt))
    catalog_path = tmp_path / "gpustack_runner" / "runner.py.json"
    fixture_path = (
        tmp_path
        / "tests"
        / "gpustack_runner"
        / "fixtures"
        / "test_list_runners_by_backend.json"
    )
    fixture_path.write_text('["original fixture"]\n')
    before = [path.read_bytes() for path in (catalog_path, fixture_path)]
    result = _run(pack, [BUILD_JOB], artifacts)
    assert result.returncode != 0, result.stdout
    assert [path.read_bytes() for path in (catalog_path, fixture_path)] == before
