"""
Promote prepared support records from validated Pack collector output.

This module is standalone and PyYAML-free so Pack's ``merge-runner`` job can
run it inside the locked ``--no-dev`` runtime environment.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version

BACKENDS = {
    "Ascend CANN": "cann",
    "Iluvatar CoreX": "corex",
    "NVIDIA CUDA": "cuda",
    "Hygon DTK": "dtk",
    "T-Head HGGC": "hggc",
    "MetaX MACA": "maca",
    "MThreads MUSA": "musa",
    "AMD ROCm": "rocm",
}
SERVICES = {"vllm", "sglang", "mindie", "voxbox"}
CANN_ALIASES = {
    "950": "950",
    "a5": "950",
    "950/a5": "950",
    "a3": "a3",
    "910c": "a3",
    "a3/910c": "a3",
    "910b": "910b",
    "310p": "310p",
}
START = "<!-- runner-support-records:start -->"
END = "<!-- runner-support-records:end -->"
COLUMNS = [
    "Backend",
    "Runtime",
    "Service",
    "Variant",
    "Engine",
    "Plugin",
    "Platforms",
    "Status",
]


class PromoteSupportError(ValueError):
    """A support document or promotion input is missing or malformed."""


DiscoveryError = PromoteSupportError


def version(value):
    if not isinstance(value, str) or not value.strip():
        msg = "version must be a nonempty string"
        raise PromoteSupportError(msg)
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise PromoteSupportError(str(exc)) from exc


def _runtime_version(backend: str, runtime: str) -> Version:
    parsed = version(runtime)
    if backend == "cann":
        # CANN support rows use major.minor runtime lines (e.g. 8.3, 8.5), while
        # catalog and matrix jobs may carry patch or rc suffixes (8.3.rc1, 8.5.0).
        return Version(f"{parsed.major}.{parsed.minor}")
    return parsed


def canonical_variant(backend, variant):
    if backend not in BACKENDS.values() or not isinstance(variant, str):
        msg = "unknown backend or variant"
        raise PromoteSupportError(msg)
    value = variant.strip().lower()
    if backend == "cann" and value in CANN_ALIASES:
        return CANN_ALIASES[value]
    if backend != "cann" and value in {"", "-"}:
        return ""
    msg = f"unknown {backend} variant: {variant}"
    raise PromoteSupportError(msg)


def _identity(backend, runtime, service, variant, engine, plugin=None):
    if service not in SERVICES:
        msg = f"unknown service: {service}"
        raise PromoteSupportError(msg)
    variant = canonical_variant(backend, variant)
    version(runtime)
    version(engine)
    if plugin is not None:
        version(plugin)
    return {
        "backend": backend,
        "runtime": runtime,
        "service": service,
        "variant": variant,
        "engine_version": engine,
        "plugin_version": plugin,
    }


def _platforms(value):
    if not isinstance(value, str):
        msg = "platforms must be a string"
        raise PromoteSupportError(msg)
    platforms = [p.strip() for p in value.split(",")]
    if (
        not platforms
        or len(set(platforms)) != len(platforms)
        or any(
            not re.fullmatch(r"linux/(amd64|arm64)(/v[0-9]+)?", p) for p in platforms
        )
    ):
        msg = "invalid or duplicate support platforms"
        raise PromoteSupportError(msg)
    return platforms


def _cells(line):
    if not line.startswith("|") or not line.endswith("|"):
        msg = "malformed support table row"
        raise PromoteSupportError(msg)
    return [cell.strip() for cell in line[1:-1].split("|")]


def _table(lines):
    if len(lines) < 2:
        msg = "missing support table header"
        raise PromoteSupportError(msg)
    header = _cells(lines[0])
    separator = _cells(lines[1])
    if len(separator) != len(header) or any(
        not re.fullmatch(r":?-{3,}:?", s) for s in separator
    ):
        msg = "malformed support table separator"
        raise PromoteSupportError(msg)
    rows = [_cells(line) for line in lines[2:]]
    if any(len(row) != len(header) for row in rows):
        msg = "support table column count differs"
        raise PromoteSupportError(msg)
    return header, rows


def _key(record):
    plugin = record["plugin_version"]
    return (
        record["backend"],
        record["service"],
        record["variant"],
        version(record["engine_version"]),
        version(plugin) if plugin is not None else None,
    )


def _explicit_records(text):
    if (
        text.count(START) != 1
        or text.count(END) != 1
        or text.index(START) > text.index(END)
    ):
        msg = "missing or duplicate support record markers"
        raise PromoteSupportError(msg)
    body = text.split(START)[1].split(END)[0]
    header, rows = _table([line.strip() for line in body.splitlines() if line.strip()])
    if header != COLUMNS:
        msg = "unexpected support record columns"
        raise PromoteSupportError(msg)
    records, seen = [], set()
    for cells in rows:
        backend, runtime, service, variant, engine, plugin, platforms, status = cells
        plugin = None if plugin == "-" else plugin
        if status not in {"prepared", "published"}:
            msg = "support status must be prepared or published"
            raise PromoteSupportError(msg)
        if (backend == "cann" and service == "vllm") != (plugin is not None):
            msg = "CANN vLLM requires an actual plugin version; other rows use -"
            raise PromoteSupportError(msg)
        record = _identity(backend, runtime, service, variant, engine, plugin)
        record.update(platforms=_platforms(platforms), status=status)
        key = (
            *_key(record),
            _runtime_version(record["backend"], runtime),
            tuple(sorted(record["platforms"])),
        )
        if key in seen:
            msg = "duplicate support identity"
            raise PromoteSupportError(msg)
        seen.add(key)
        records.append(record)
    return records


def _legacy_records(text):
    records = []
    for heading, section in re.findall(
        r"^### ([^\n]+)\n(.*?)(?=^#{1,3} |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        if heading not in BACKENDS:
            continue
        backend = BACKENDS[heading]
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        header, rows = _table(lines)
        services = [cell.lower() for cell in header[1:]]
        for cells in rows:
            runtime = re.fullmatch(r"([\d.]+)(?: \(([^)]+)\))?", cells[0])
            if runtime is None:
                msg = "malformed historical runtime or variant"
                raise PromoteSupportError(msg)
            for service, cell in zip(services, cells[1:], strict=False):
                # Parse only version cells in known backend/service tables.
                clean = re.sub(r"<br\s*/?>|\*\*|~~", "", cell).strip()
                for token in clean.split(",") if clean else []:
                    match = re.fullmatch(r"\s*`([^`]+)`\s*(\(rc\))?\s*", token)
                    if match is None:
                        msg = "malformed historical engine cell"
                        raise PromoteSupportError(msg)
                    record = _identity(
                        backend,
                        runtime[1],
                        service,
                        runtime[2] or "",
                        match[1],
                    )
                    record.update(platforms=[], status="historical")
                    records.append(record)
    return records


def parse_support(text, *, require_explicit=False):
    """Read explicit records and retained historical tables, never prose mentions."""
    explicit = (
        _explicit_records(text)
        if require_explicit or START in text or END in text
        else []
    )
    legacy = _legacy_records(text)
    if START not in text and not legacy:
        msg = "no structured support tables found"
        raise PromoteSupportError(msg)
    return explicit + legacy


def _installed_engine_matches(job, installed):
    measured, expected = version(installed), version(job["service_version"])
    if measured == expected:
        return True
    # Upstream vLLM setup.py adds accelerator build identifiers to releases;
    # vllm-ascend builds with VLLM_TARGET_DEVICE=empty (e.g. 0.27.1+empty).
    # Compare the public release without discarding rc/post/dev components.
    suffix = {"cuda": r"cu[0-9]+", "rocm": r"rocm[0-9]+", "cann": r"empty"}.get(
        job["backend"],
    )
    return bool(
        job["service"] == "vllm"
        and suffix
        and expected.local is None
        and re.fullmatch(suffix, measured.local or "")
        and version(measured.public) == expected,
    )


def promote_support(text, jobs, dependencies):
    """
    Promote only coverage in this invocation's validated collector output.

    The Bash caller supplies ``dependencies`` only after ``catalog`` validates
    independent Package records, receipts, and current registry manifests.
    Missing collection results and development tags cannot promote a row.
    """
    parse_support(text)
    records = _explicit_records(text)
    measured = []
    for job in jobs:
        if job["platform_tag"] not in dependencies or job["tag"].endswith("-dev"):
            continue
        packages = dependencies[job["platform_tag"]]
        # The matrix declares intent. Only the collected service distribution
        # can confirm the engine release. Keep its raw build version in metadata.
        try:
            installed = packages.get(job["service"])
            if not _installed_engine_matches(job, installed):
                continue
        except PromoteSupportError:
            continue
        measured.append(
            _identity(
                job["backend"],
                job["backend_version"],
                job["service"],
                job["backend_variant"],
                job["service_version"],
                packages.get("vllm-ascend")
                if job["backend"] == "cann" and job["service"] == "vllm"
                else None,
            )
            | {"platform": job["platform"]},
        )
    lines = text.splitlines(keepends=True)
    record_index = 0
    inside = False
    for index, line in enumerate(lines):
        if line.strip() == START:
            inside = True
        elif line.strip() == END:
            inside = False
        elif (
            inside
            and line.strip().startswith("|")
            and _cells(line.strip())[0] in BACKENDS.values()
        ):
            record = records[record_index]
            record_index += 1
            covered = {
                row["platform"]
                for row in measured
                if _key(row) == _key(record)
                and _runtime_version(record["backend"], row["runtime"])
                == _runtime_version(record["backend"], record["runtime"])
            }
            if record["status"] == "prepared" and set(record["platforms"]) <= covered:
                lines[index] = re.sub(r"\bprepared(?=\s*\|\s*$)", "published", line)
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    promote = commands.add_parser("promote")
    for name in ("support", "context", "dependencies", "output"):
        promote.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        text = promote_support(
            args.support.read_text(encoding="utf-8"),
            json.loads(args.context.read_text(encoding="utf-8"))["matrix"][
                "build_jobs"
            ],
            json.loads(args.dependencies.read_text(encoding="utf-8")),
        )
        args.output.write_text(text, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"support promotion failed: {exc}\n")


if __name__ == "__main__":
    main()
