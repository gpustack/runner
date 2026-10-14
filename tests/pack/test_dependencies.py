"""Self-consistency tests for pack/dependencies.json.

The file maps each dependency name to ordered distribution aliases, highest
priority first. An alias is a distribution name, or a prefix pattern: a name
stem ending in `-` plus one trailing `*`. Central collection reads installed
versions from each final platform image. Catalog preparation folds validated
results onto these names. Query code reads the folded result from
`runner.py.json`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES_FILE = REPO_ROOT / "pack" / "dependencies.json"

DEPENDENCIES: dict[str, list[str]] = json.loads(
    DEPENDENCIES_FILE.read_text(encoding="utf-8"),
)

ALL_ALIASES = [package for packages in DEPENDENCIES.values() for package in packages]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _alias_anchor(package: str) -> str:
    """What an alias can record: the name itself, or its pattern stem."""
    return package.removesuffix("*")


def test_discovery_found_dependencies():
    # If this ever comes back empty, every test below passes vacuously.
    assert DEPENDENCIES, f"no dependency names found in {DEPENDENCIES_FILE}"


@pytest.mark.parametrize("name, packages", list(DEPENDENCIES.items()))
def test_packages_non_empty(name, packages):
    assert packages, f"case {name} expected a non-empty package list"


@pytest.mark.parametrize("package", ALL_ALIASES)
def test_package_names_are_pep503_normalized(package):
    # The probe normalizes what `pip list` reports before intersecting, so a
    # non-normalized name here could never match. Pattern aliases are checked
    # by their stem, without the trailing `*`.
    stem = _alias_anchor(package)
    assert _normalize(stem) == stem, (
        f"case {package} expected an already PEP 503 normalized package name"
    )


@pytest.mark.parametrize(
    "package",
    [package for package in ALL_ALIASES if package.endswith("*")],
)
def test_pattern_stems_end_with_dash(package):
    # Prefix matching must stay component-aligned: a stem ending in '-' never
    # matches the bare name and cannot capture lookalikes such as `torchvision`
    # under a `torch-*` stem.
    assert package[:-1].endswith("-"), (
        f"case {package} expected a pattern stem ending in '-'"
    )


def test_dependency_names_are_sorted():
    names = list(DEPENDENCIES.keys())
    assert names == sorted(names), (
        "expected top-level dependency names to be sorted lexicographically"
    )


def test_package_names_are_globally_unique():
    # Two dependency names must never be able to claim the same installed
    # distribution: one of them would report a version for a package it does
    # not actually describe. A pattern claims every distribution under its
    # stem, so pattern anchors overlap when one starts with the other, a
    # literal collides with a stem it starts with, and plain names collide
    # only on equality.
    anchors = [
        (name, _alias_anchor(package), package.endswith("*"))
        for name, packages in DEPENDENCIES.items()
        for package in packages
    ]
    conflicts = []
    for index, (name, anchor, pattern) in enumerate(anchors):
        for other_name, other, other_pattern in anchors[index + 1 :]:
            if name == other_name:
                continue
            if pattern and other_pattern:
                overlap = other.startswith(anchor) or anchor.startswith(other)
            elif pattern or other_pattern:
                literal, stem = (other, anchor) if pattern else (anchor, other)
                overlap = literal.startswith(stem)
            else:
                overlap = anchor == other
            if overlap:
                conflicts.append(
                    f"{anchor!r} ({name!r}) overlaps {other!r} ({other_name!r})",
                )
    assert not conflicts, f"expected no cross-key alias overlaps, found: {conflicts}"
