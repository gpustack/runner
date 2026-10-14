"""Execute the real probe against fabricated site-packages.

The probe runs inside the final image, where vendor toolkits add their own
distribution directories (CANN ships a duplicate ``mindstudio-opst``), so these
tests build that state on ``PYTHONPATH`` instead of mocking importlib.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROBE = Path(__file__).resolve().parents[2] / "pack" / "probe_dependencies.py"


def _dist_info(root: Path, name: str, version: str) -> None:
    info = root / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    info.joinpath("METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def _probe(
    tmp_path: Path,
    mapping: dict[str, list[str]],
) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - the repository probe with fixture metadata.
        [sys.executable, str(PROBE)],
        input=json.dumps(mapping),
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_unmapped_conflict_does_not_fail_collection(tmp_path):
    _dist_info(tmp_path, "mindstudio-opst", "9.1.0")
    _dist_info(tmp_path, "mindstudio-opst", "7.0.0")
    result = _probe(tmp_path, {"vllm": ["vllm"]})
    assert result.returncode == 0, result.stderr
    assert "mindstudio-opst" not in json.loads(result.stdout)["distributions"]
    # The duplicate is genuinely visible to the probe; only the mapping gates it.
    visible = _probe(tmp_path, {"mindstudio-opst": ["mindstudio-opst"]})
    assert visible.returncode == 1
    assert "conflicting installed distribution versions" in visible.stderr


def test_mapped_conflict_still_fails_collection(tmp_path):
    _dist_info(tmp_path, "mindstudio-opst", "9.1.0")
    _dist_info(tmp_path, "mindstudio-opst", "7.0.0")
    result = _probe(
        tmp_path,
        {"vllm": ["vllm"], "mindstudio-opst": ["mindstudio-opst"]},
    )
    assert result.returncode == 1
    assert (
        "conflicting installed distribution versions: mindstudio-opst" in result.stderr
    )


def test_pattern_records_variant_and_excludes_lookalike(tmp_path):
    # A stem ends with '-', so the lookalike that breaks at the dash boundary
    # stays unclaimed while the real variant under the stem is recorded.
    _dist_info(tmp_path, "acme-npu", "0.3.7.post1")
    _dist_info(tmp_path, "acmex", "1.0")
    result = _probe(tmp_path, {"acme": ["acme-*"]})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["distributions"] == {
        "acme-npu": "0.3.7.post1",
    }


def test_literal_still_recorded_alongside_pattern(tmp_path):
    _dist_info(tmp_path, "acme", "1.0")
    _dist_info(tmp_path, "acme-npu", "0.3.7.post1")
    result = _probe(tmp_path, {"acme": ["acme-*", "acme"]})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["distributions"] == {
        "acme": "1.0",
        "acme-npu": "0.3.7.post1",
    }


def test_pattern_matched_conflict_fails_collection(tmp_path):
    _dist_info(tmp_path, "acme-npu", "0.3.7.post1")
    _dist_info(tmp_path, "Acme.NPU", "0.3.6")
    result = _probe(tmp_path, {"acme": ["acme-*"]})
    assert result.returncode == 1
    assert "conflicting installed distribution versions: acme-npu" in result.stderr


def test_unmatched_conflict_ignored_under_pattern_mapping(tmp_path):
    _dist_info(tmp_path, "unrelated", "1.0")
    _dist_info(tmp_path, "unrelated", "2.0")
    result = _probe(tmp_path, {"acme": ["acme-*"]})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["distributions"] == {}
