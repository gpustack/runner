"""
Advisory draft checker for stage sessions; controller validation stays the only gate.

The checker re-runs the controller's own validators against a trusted seed
in .autosync/seed/ with no network, registry, GitHub, or subprocess access.
Every completed check exits 0 and reports INVALID as data, so a failing
draft can never trip the tool guard; only an unusable environment exits 3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.auto_sync import assemble, proposal

ADVISORY_NOTE = (
    "Advisory only: discovery binding and group patch apply checks run in the "
    "controller, never here."
)

SEEDS = {
    "analysis": ("identity.json", "discovery.json", "evidence.json"),
    "proposal": ("identity.json", "permissions.json"),
}

SEED_SHAPES = {
    "identity.json": dict,
    "discovery.json": list,
    "evidence.json": dict,
    "permissions.json": dict,
}


def _load_seed(seed: Path, stage: str) -> tuple[dict, str | None]:
    """Return (values, problem); a problem marks the environment unusable."""
    values: dict = {}
    name = ""
    try:
        for name in SEEDS[stage]:
            data = json.loads((seed / name).read_text(encoding="utf-8"))
            if not isinstance(data, SEED_SHAPES[name]):
                return {}, f"{name}: unexpected seed shape"
            values[name] = data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"{name}: {exc}"
    if stage == "proposal":
        try:
            payload = values["permissions.json"]
            values["engine_prereleases"] = {
                tuple(item) for item in payload["engine_prereleases"]
            }
            values["prerelease_packages"] = set(payload["prerelease_packages"])
        except (TypeError, KeyError) as exc:
            return {}, f"permissions.json: {exc}"
    return values, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--stage", required=True, choices=tuple(SEEDS))
    args = parser.parse_args(argv)
    values, problem = _load_seed(Path.cwd() / ".autosync" / "seed", args.stage)
    if problem:
        print(f"CHECKER UNAVAILABLE: {problem}")
        return 3
    try:
        data = proposal.parse_reply(sys.stdin.read())
        if args.stage == "analysis":
            proposal.validate_analysis(
                data,
                values["identity.json"],
                found=values["discovery.json"],
                evidence=values["evidence.json"],
            )
        else:
            proposal.validate_proposal(
                assemble.assemble(data, Path.cwd()),
                values["identity.json"],
                engine_prereleases=values["engine_prereleases"],
                prerelease_packages=values["prerelease_packages"],
            )
    except proposal.ProposalError as exc:
        print(f"INVALID: {exc}")
        return 0
    print("VALID")
    print(ADVISORY_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
