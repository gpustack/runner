"""
Assemble a proposal from a JSON draft whose groups reference patch files.

A group may use "patch_file" instead of "patch". The file is read as UTF-8 data,
relative paths resolve against the draft directory, and nothing else changes.
Semantic validation stays with the trusted controller.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.auto_sync.proposal import ProposalError, load_json, require


def assemble(draft, base: Path):
    require(isinstance(draft, dict), "draft must be an object")
    groups = draft.get("groups")
    if groups is None:
        return draft
    require(isinstance(groups, list), "groups must be a list")
    for group in groups:
        require(isinstance(group, dict), "group must be an object")
        if "patch_file" not in group:
            continue
        require("patch" not in group, "group has both patch and patch_file")
        name = group["patch_file"]
        require(isinstance(name, str) and name, "patch_file must be a string")
        try:
            group["patch"] = (base / name).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            msg = f"cannot read patch_file {name}: {exc}"
            raise ProposalError(msg) from exc
        del group["patch_file"]
    return draft


def assemble_file(draft_path, output_path) -> None:
    draft_path = Path(draft_path)
    try:
        text = draft_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read draft: {exc}"
        raise ProposalError(msg) from exc
    result = assemble(load_json(text), draft_path.parent)
    try:
        Path(output_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        msg = f"cannot write output: {exc}"
        raise ProposalError(msg) from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--draft", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        assemble_file(args.draft, args.output)
    except ProposalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
