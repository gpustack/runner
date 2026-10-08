"""Validate queued concurrency before linting temporary workflow copies."""

from __future__ import annotations

import argparse
import copy
import json
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
        keys = set()
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
    # Work on YAML nodes so keys such as `on` and all other scalar values survive.
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


def _binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        msg = f"required tool is unavailable: {name}"
        raise ValueError(msg)
    return binary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflows", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        actionlint = _binary("actionlint")
        shellcheck = _binary("shellcheck")
        pin = json.loads(Path(__file__).with_name("tool-versions.json").read_text())[
            "tools"
        ]["actionlint"]["version"]
        version = subprocess.run(  # noqa: S603 - resolved tool and fixed arguments.
            [actionlint, "-version"],
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout.splitlines()
        if not version or version[0] != pin:
            msg = f"actionlint must match pinned version {pin}"
            raise ValueError(msg)  # noqa: TRY301 - Pin failures use the same CLI error path.
        command = [actionlint, "-shellcheck", shellcheck]
        config = Path(".github/actionlint.yaml").resolve()
        if config.is_file():
            command.extend(["-config-file", str(config)])
        failed = False
        for path in args.workflows:
            try:
                source = _prepare(path.read_text())
                with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as temporary:
                    temporary.write(source)
                    temporary.seek(0)
                    # The original filename retains project context and useful diagnostics.
                    result = subprocess.run(  # noqa: S603 - source goes only to stdin.
                        [*command, "-stdin-filename", str(path.resolve()), "-"],
                        stdin=temporary,
                        check=False,
                        timeout=300,
                    )
                failed |= result.returncode != 0
            except (  # noqa: PERF203 - Continue checking other workflows after a failure.
                OSError,
                ValueError,
                yaml.YAMLError,
                subprocess.TimeoutExpired,
            ) as exc:
                print(f"{path}: {exc}", file=sys.stderr)
                failed = True
        return int(failed)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"workflow lint failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
