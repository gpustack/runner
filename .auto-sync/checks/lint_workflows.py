"""Validate workflow YAML, duplicate keys, and queued concurrency before optional actionlint."""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


def _fields(node: Node | None) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        return {}
    return {
        key.value: value for key, value in node.value if isinstance(key, ScalarNode)
    }


def _duplicates(node: Node, seen: set[int]) -> None:
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if isinstance(key, ScalarNode):
                if key.value in keys:
                    msg = f"duplicate mapping key {key.value!r} at line {key.start_mark.line + 1}"
                    raise ValueError(msg)
                keys.add(key.value)
            _duplicates(key, seen)
            _duplicates(value, seen)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _duplicates(value, seen)


def _queue(node: Node) -> Node:
    fields = _fields(node)
    if "queue" not in fields:
        return node
    queue = fields["queue"]
    if (
        not isinstance(queue, ScalarNode)
        or queue.tag != "tag:yaml.org,2002:str"
        or queue.value not in {"single", "max"}
    ):
        msg = "concurrency.queue must be a literal string: single or max"
        raise ValueError(msg)
    if queue.value == "max" and "cancel-in-progress" in fields:
        cancel = fields["cancel-in-progress"]
        if (
            not isinstance(cancel, ScalarNode)
            or cancel.tag != "tag:yaml.org,2002:bool"
            or cancel.value.lower() != "false"
        ):
            msg = "concurrency.queue: max requires cancel-in-progress absent or literal false"
            raise ValueError(msg)
    result = copy.copy(node)
    result.value = [
        (key, value)
        for key, value in node.value
        if not isinstance(key, ScalarNode) or key.value != "queue"
    ]
    return result


def _prepare(source: str) -> str:
    node = yaml.compose(source, Loader=yaml.SafeLoader)
    if node is None:
        return source
    _duplicates(node, set())
    fields = _fields(node)
    for scope in [node, *_fields(fields.get("jobs")).values()]:
        if isinstance(scope, MappingNode):
            scope.value = [
                (
                    key,
                    _queue(value)
                    if isinstance(key, ScalarNode) and key.value == "concurrency"
                    else value,
                )
                for key, value in scope.value
            ]
    return yaml.serialize(node)


def _lint_one(
    path: Path,
    *,
    run_actionlint: bool,
    command: list[str],
) -> bool:
    try:
        source = _prepare(path.read_text(encoding="utf-8"))
        if not run_actionlint:
            return False
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as temporary:
            temporary.write(source)
            temporary.seek(0)
            result = subprocess.run(  # noqa: S603 - resolved binary and stdin source.
                [*command, "-stdin-filename", str(path.resolve()), "-"],
                stdin=temporary,
                check=False,
                timeout=300,
            )
    except (OSError, ValueError, yaml.YAMLError, subprocess.TimeoutExpired) as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return True
    return result.returncode != 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-actionlint",
        action="store_true",
        help="Fail if actionlint or shellcheck is missing.",
    )
    parser.add_argument("workflows", nargs="+", type=Path)
    args = parser.parse_args(argv)

    actionlint = shutil.which("actionlint")
    shellcheck = shutil.which("shellcheck")
    ci_mode = os.environ.get("CI", "").lower() == "true"

    if args.require_actionlint and (actionlint is None or shellcheck is None):
        missing = "actionlint" if actionlint is None else "shellcheck"
        print(
            f"workflow lint failed: required tool is unavailable: {missing}",
            file=sys.stderr,
        )
        return 1
    if ci_mode and actionlint is not None and shellcheck is None:
        print(
            "workflow lint failed: required tool is unavailable: shellcheck",
            file=sys.stderr,
        )
        return 1

    run_actionlint = actionlint is not None and shellcheck is not None
    command = [actionlint, "-shellcheck", shellcheck] if run_actionlint else []
    if run_actionlint:
        config = Path(".github/actionlint.yaml").resolve()
        if config.is_file():
            command.extend(["-config-file", str(config)])

    failed = False
    for path in args.workflows:
        failed |= _lint_one(path, run_actionlint=run_actionlint, command=command)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
