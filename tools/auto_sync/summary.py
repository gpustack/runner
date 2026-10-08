"""Render compact Actions summaries from the controller's result files."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from tools.auto_sync.proposal import REPOSITORY, load_json


def _cell(value, limit=300):
    text = " ".join(str(value).split())
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    if len(text) > limit:
        text = text[:limit] + "..."
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_\[\]|])", r"\\\1", text)


def _elapsed(value):
    if value is None:
        return "Not recorded"
    if value < 60:
        return f"{value:.1f}s"
    minutes, seconds = divmod(round(value), 60)
    return f"{minutes}m {seconds}s"


def _reason(value):
    if "Reached max session turns" in value:
        return "Qwen reached the session turn limit (exit 53)."
    return _cell(value)


def tools_markdown(data):
    cache = "Hit" if data["cache_hit"] else "Miss"
    elapsed = _elapsed(data["duration_seconds"])
    return (
        "### Tool installation\n\n"
        "| Cache | Verification / installation |\n"
        "| --- | --- |\n"
        f"| {cache} | {elapsed} |\n\n"
    )


def result_markdown(data, context):
    stage = data["stage"]
    label = {
        "prepare": "Discovery",
        "research": "Research",
        "validate": "Validation",
        "publish": "Publication",
    }.get(stage, stage)
    elapsed = _elapsed(data.get("durations", {}).get(stage + "_seconds"))
    lines = [
        "### Release synchronization",
        "",
        f"**{_cell(data['status'].upper())}** · {_cell(label)} · {elapsed}",
        "",
        _reason(data["reason"]),
        "",
    ]
    discovered = {
        candidate["subscription"]: candidate
        for candidate in data.get("discovery", context.get("discovery", []))
    }
    candidates = data.get("candidates", [])
    if candidates:
        lines.extend(
            [
                "| Subscription | Latest engine | Latest plugin | Outcome |",
                "| --- | --- | --- | --- |",
            ],
        )
        for candidate in candidates:
            selected = discovered.get(candidate["subscription"], {})
            cells = [
                candidate["subscription"],
                selected.get("engine_version", "Unknown"),
                selected.get("plugin_version") or "-",
                candidate["status"].upper(),
            ]
            lines.append("| " + " | ".join(map(_cell, cells)) + " |")
        notes = [
            f"- {_cell(candidate['subscription'])}: {_reason(candidate['reason'])}"
            for candidate in candidates
            if candidate.get("reason") and candidate["reason"] != data["reason"]
        ]
        if notes:
            lines.extend(["", *notes])
        lines.append("")
    number = data.get("pr_number")
    repository = context.get("identity", {}).get("repository", "")
    if type(number) is int and number > 0 and re.fullmatch(REPOSITORY, repository):
        lines.extend(
            [
                f"Pull request: [#{number}](https://github.com/{repository}/pull/{number})",
                "",
            ],
        )
    lines.extend(
        ["Detailed results and diagnostics are in the workflow artifacts.", ""],
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--tools", type=Path)
    inputs.add_argument("--result", type=Path)
    parser.add_argument("--context", type=Path)
    args = parser.parse_args(argv)
    if args.tools:
        output = tools_markdown(load_json(args.tools.read_text()))
    else:
        context = (
            load_json(args.context.read_text())
            if args.context and args.context.is_file()
            else {}
        )
        output = result_markdown(load_json(args.result.read_text()), context)
    print(output, end="")


if __name__ == "__main__":
    main()
