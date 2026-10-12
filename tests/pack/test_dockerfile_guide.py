"""Require a leading upgrade-guide header on every subscribed recipe.

Auto-sync extracts the leading `## Upgrade guide:` block of each subscribed
`pack/<backend>/Dockerfile.<service>` at the frozen default revision and
injects it into stage prompts. A subscribed recipe without that header runs
without its maintainer-declared upgrade constraints, so the suite fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.auto_sync.discovery import SUBSCRIPTIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "pack"
GUIDE_MARKER = "## Upgrade guide:"


def _has_leading_guide(text: str) -> bool:
    """True when the top contiguous ``##`` block opens with the guide marker."""
    first = next(iter(text.splitlines()), "")
    return first.startswith(GUIDE_MARKER)


def test_subscriptions_exist():
    # An empty subscription list would make the gate below pass vacuously.
    assert SUBSCRIPTIONS, "no subscriptions found in tools/auto_sync/discovery.py"


@pytest.mark.parametrize(
    "backend,service",
    [(backend, service) for backend, service, _ in SUBSCRIPTIONS],
)
def test_subscribed_recipe_carries_leading_upgrade_guide(backend, service):
    path = PACK_DIR / backend / f"Dockerfile.{service}"
    text = path.read_text(encoding="utf-8")
    assert _has_leading_guide(text), (
        f"{path} must open with a '{GUIDE_MARKER}' block; auto-sync injects "
        "that header as the recipe's declared upgrade guidance"
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("## Upgrade guide: re-check every pin.\nARG A=1\n", True),
        ("## Upgrade guide:\n## - one constraint line\nARG A=1\n", True),
        ("ARG A=1\n## Upgrade guide: mid-file lines never count\n", False),
        ("## Notes:\n## Upgrade guide: not the block's first line\n", False),
        ("# single-hash opener\n## Upgrade guide: block starts later\n", False),
        ("", False),
    ],
)
def test_leading_guide_detection(text, expected):
    assert _has_leading_guide(text) is expected
