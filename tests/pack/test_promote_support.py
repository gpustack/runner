"""Tests for standalone PyYAML-free support-record promotion in pack/promote_support.py."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Subprocess calls invoke sys.executable on fixed repository paths and temporary files.
# ruff: noqa: S603

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "pack" / "promote_support.py"

SPEC = importlib.util.spec_from_file_location("promote_support", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
promote_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(promote_mod)

HEADER = (
    "# Support Records\n\n"
    "<!-- runner-support-records:start -->\n"
    "| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "{rows}"
    "<!-- runner-support-records:end -->\n"
)


def _row(
    *,
    backend="cuda",
    runtime="13.0",
    service="vllm",
    variant="-",
    engine="0.33.0",
    plugin="-",
    platforms="linux/amd64",
    status="prepared",
):
    return (
        f"| {backend} | {runtime} | {service} | {variant} | "
        f"{engine} | {plugin} | {platforms} | {status} |\n"
    )


def _job(
    *,
    backend="cuda",
    backend_version="13.0",
    service="vllm",
    backend_variant="",
    service_version="0.33.0",
    platform="linux/amd64",
    platform_tag="cuda-vllm-linux-amd64",
    tag="cuda-vllm",
):
    return {
        "backend": backend,
        "backend_version": backend_version,
        "service": service,
        "backend_variant": backend_variant,
        "service_version": service_version,
        "platform": platform,
        "platform_tag": platform_tag,
        "tag": tag,
    }


def test_prepared_promotes_to_published_when_all_platforms_measured():
    support = HEADER.format(
        rows=(
            _row(platforms="linux/amd64, linux/arm64", status="prepared")
            + _row(
                service="sglang",
                engine="0.5.23",
                platforms="linux/amd64",
                status="published",
            )
        ),
    )
    jobs = [
        _job(platform="linux/amd64", platform_tag="cuda-vllm-linux-amd64"),
        _job(platform="linux/arm64", platform_tag="cuda-vllm-linux-arm64"),
    ]
    dependencies = {
        "cuda-vllm-linux-amd64": {"vllm": "0.33.0+cu130"},
        "cuda-vllm-linux-arm64": {"vllm": "0.33.0"},
    }
    promoted = promote_mod.promote_support(support, jobs, dependencies)
    assert "0.33.0 | - | linux/amd64, linux/arm64 | published |" in promoted
    assert "0.5.23 | - | linux/amd64 | published |" in promoted


def test_partial_platform_coverage_retains_prepared_status():
    support = HEADER.format(
        rows=_row(platforms="linux/amd64, linux/arm64", status="prepared"),
    )
    jobs = [
        _job(platform="linux/amd64", platform_tag="cuda-vllm-linux-amd64"),
        _job(platform="linux/arm64", platform_tag="cuda-vllm-linux-arm64"),
    ]
    dependencies = {
        "cuda-vllm-linux-amd64": {"vllm": "0.33.0"},
    }
    promoted = promote_mod.promote_support(support, jobs, dependencies)
    assert promoted == support
    assert "linux/amd64, linux/arm64 | prepared |" in promoted


@pytest.mark.parametrize(
    "jobs, dependencies",
    [
        (
            [_job(tag="cuda-vllm-dev")],
            {"cuda-vllm-linux-amd64": {"vllm": "0.33.0"}},
        ),
        (
            [_job(platform_tag="cuda-vllm-linux-amd64")],
            {},
        ),
    ],
)
def test_dev_tags_and_missing_platform_tag_do_not_promote(jobs, dependencies):
    support = HEADER.format(rows=_row(platforms="linux/amd64", status="prepared"))
    promoted = promote_mod.promote_support(support, jobs, dependencies)
    assert promoted == support


@pytest.mark.parametrize(
    "installed, expected_promoted",
    [
        ({"vllm": "0.27.1+empty", "vllm-ascend": "0.27.1rc1"}, True),
        ({"vllm": "0.27.1", "vllm-ascend": "0.27.1rc1"}, True),
        ({"vllm": "0.27.2+empty", "vllm-ascend": "0.27.1rc1"}, False),
        ({"vllm": "0.27.1+cu130", "vllm-ascend": "0.27.1rc1"}, False),
        ({"vllm": "0.27.1+empty", "vllm-ascend": "0.27.2rc1"}, False),
        ({"vllm": "0.27.1+empty"}, False),
    ],
)
def test_cann_vllm_requires_matching_engine_and_ascend_plugin(
    installed,
    expected_promoted,
):
    support = HEADER.format(
        rows=_row(
            backend="cann",
            runtime="9.1",
            service="vllm",
            variant="910b",
            engine="0.27.1",
            plugin="0.27.1rc1",
            platforms="linux/amd64",
            status="prepared",
        ),
    )
    job = _job(
        backend="cann",
        backend_version="9.1",
        service="vllm",
        backend_variant="910b",
        service_version="0.27.1",
        platform="linux/amd64",
        platform_tag="cann-9.1-910b-vllm-linux-amd64",
        tag="cann-vllm",
    )
    promoted = promote_mod.promote_support(
        support,
        [job],
        {job["platform_tag"]: installed},
    )
    expected_status = "published" if expected_promoted else "prepared"
    assert f"0.27.1 | 0.27.1rc1 | linux/amd64 | {expected_status} |" in promoted


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("950/A5", "950"),
        ("A3/910C", "a3"),
        ("910B", "910b"),
        ("310P", "310p"),
        ("a5", "950"),
        ("910c", "a3"),
    ],
)
def test_cann_variant_alias_canonicalization(raw, expected):
    assert promote_mod.canonical_variant("cann", raw) == expected


@pytest.mark.parametrize(
    "support_variant, job_variant",
    [
        ("A3/910C", "910c"),
        ("950/A5", "950"),
    ],
)
def test_cann_variant_alias_promotes_matching_record(support_variant, job_variant):
    support = HEADER.format(
        rows=_row(
            backend="cann",
            runtime="9.1",
            service="vllm",
            variant=support_variant,
            engine="0.27.1",
            plugin="0.27.1rc1",
            platforms="linux/arm64",
            status="prepared",
        ),
    )
    canonical = promote_mod.canonical_variant("cann", support_variant)
    job = _job(
        backend="cann",
        backend_version="9.1",
        service="vllm",
        backend_variant=job_variant,
        service_version="0.27.1",
        platform="linux/arm64",
        platform_tag=f"cann-9.1-{canonical}-vllm-linux-arm64",
        tag="cann-vllm",
    )
    promoted = promote_mod.promote_support(
        support,
        [job],
        {job["platform_tag"]: {"vllm": "0.27.1+empty", "vllm-ascend": "0.27.1rc1"}},
    )
    assert (
        f"{support_variant} | 0.27.1 | 0.27.1rc1 | linux/arm64 | published |"
        in promoted
    )


@pytest.mark.parametrize(
    "support_runtime, job_runtime",
    [
        ("8.5", "8.5.0"),
        ("8.5.0", "8.5"),
        ("8.3", "8.3.rc1"),
        ("8.3.rc1", "8.3"),
    ],
)
def test_cann_runtime_alias_promotes_matching_record(support_runtime, job_runtime):
    support = HEADER.format(
        rows=_row(
            backend="cann",
            runtime=support_runtime,
            service="vllm",
            variant="910b",
            engine="0.18.0",
            plugin="0.18.0",
            platforms="linux/arm64",
            status="prepared",
        ),
    )
    job = _job(
        backend="cann",
        backend_version=job_runtime,
        service="vllm",
        backend_variant="910b",
        service_version="0.18.0",
        platform="linux/arm64",
        platform_tag=f"cann-{job_runtime}-910b-vllm-linux-arm64",
        tag="cann-vllm",
    )
    promoted = promote_mod.promote_support(
        support,
        [job],
        {job["platform_tag"]: {"vllm": "0.18.0+empty", "vllm-ascend": "0.18.0"}},
    )
    assert (
        f"| cann | {support_runtime} | vllm | 910b | 0.18.0 | 0.18.0 | linux/arm64 | published |"
        in promoted
    )


def test_cann_runtime_alias_duplicate_detection():
    support = HEADER.format(
        rows=(
            _row(
                backend="cann",
                runtime="8.3",
                service="vllm",
                variant="910b",
                engine="0.12.0",
                plugin="0.12.0rc1",
                platforms="linux/arm64",
                status="prepared",
            )
            + _row(
                backend="cann",
                runtime="8.3.rc1",
                service="vllm",
                variant="910b",
                engine="0.12.0",
                plugin="0.12.0rc1",
                platforms="linux/arm64",
                status="prepared",
            )
        ),
    )
    with pytest.raises(promote_mod.PromoteSupportError, match="duplicate"):
        promote_mod.parse_support(support, require_explicit=True)


def test_canonical_variant_rejects_unknown_values():
    with pytest.raises(promote_mod.DiscoveryError):
        promote_mod.canonical_variant("cann", "unknown")
    with pytest.raises(promote_mod.DiscoveryError):
        promote_mod.canonical_variant("cuda", "910b")


def test_cli_promote_subcommand_end_to_end(tmp_path):
    support_file = tmp_path / "support.md"
    context_file = tmp_path / "context.json"
    dependencies_file = tmp_path / "dependencies.json"
    output_file = tmp_path / "output.md"

    support_file.write_text(
        HEADER.format(rows=_row(platforms="linux/amd64", status="prepared")),
        encoding="utf-8",
    )
    context_file.write_text(
        json.dumps({"matrix": {"build_jobs": [_job()]}}),
        encoding="utf-8",
    )
    dependencies_file.write_text(
        json.dumps({"cuda-vllm-linux-amd64": {"vllm": "0.33.0+cu130"}}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "promote",
            "--support",
            str(support_file),
            "--context",
            str(context_file),
            "--dependencies",
            str(dependencies_file),
            "--output",
            str(output_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "0.33.0 | - | linux/amd64 | published |" in output_file.read_text(
        encoding="utf-8",
    )


def test_cli_promote_fails_on_malformed_input(tmp_path):
    support_file = tmp_path / "support.md"
    context_file = tmp_path / "context.json"
    dependencies_file = tmp_path / "dependencies.json"
    output_file = tmp_path / "output.md"

    support_file.write_text("not a support table\n", encoding="utf-8")
    context_file.write_text(
        json.dumps({"matrix": {"build_jobs": []}}),
        encoding="utf-8",
    )
    dependencies_file.write_text("{}", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "promote",
            "--support",
            str(support_file),
            "--context",
            str(context_file),
            "--dependencies",
            str(dependencies_file),
            "--output",
            str(output_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "support promotion failed:" in result.stderr
    assert not output_file.exists()


def test_module_is_pyyaml_and_gpustack_runner_free(monkeypatch):
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "yaml" not in imported
    assert "gpustack_runner" not in imported

    monkeypatch.setitem(sys.modules, "yaml", None)
    monkeypatch.setitem(sys.modules, "gpustack_runner", None)
    spec = importlib.util.spec_from_file_location(
        "promote_support_isolated",
        MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    assert isolated.DiscoveryError is isolated.PromoteSupportError
