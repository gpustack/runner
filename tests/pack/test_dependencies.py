"""Self-consistency tests for pack/dependencies.json.

The file maps a dependency name to the distribution names it may ship under,
highest priority first. It is read twice, both on the build side: `pack.yml`
flattens the values into the probe's build argument, and `pack/merge_runner.sh`
folds a probe result back onto the names. Nothing reads it at query time --
`runner.py.json` already carries the folded result.
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


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_discovery_found_dependencies():
    # If this ever comes back empty, every test below passes vacuously.
    assert DEPENDENCIES, f"no dependency names found in {DEPENDENCIES_FILE}"


@pytest.mark.parametrize("name, packages", list(DEPENDENCIES.items()))
def test_packages_non_empty(name, packages):
    assert packages, f"case {name} expected a non-empty package list"


@pytest.mark.parametrize(
    "package",
    [package for packages in DEPENDENCIES.values() for package in packages],
)
def test_package_names_are_pep503_normalized(package):
    # The probe normalizes what `pip list` reports before intersecting, so a
    # non-normalized name here could never match.
    assert _normalize(package) == package, (
        f"case {package} expected an already PEP 503 normalized package name"
    )


def test_dependency_names_are_sorted():
    names = list(DEPENDENCIES.keys())
    assert names == sorted(names), (
        "expected top-level dependency names to be sorted lexicographically"
    )


def test_package_names_are_globally_unique():
    # A distribution belonging to two dependency names would be folded into
    # both, so one of them would report a version for a package it does not
    # actually describe.
    seen: dict[str, str] = {}
    duplicates = []
    for name, packages in DEPENDENCIES.items():
        for package in packages:
            if package in seen:
                duplicates.append(
                    f"{package} appears under both {seen[package]!r} and {name!r}",
                )
            else:
                seen[package] = name
    assert not duplicates, (
        f"expected no duplicate package names across dependency names, "
        f"found: {duplicates}"
    )
