"""
Select latest releases against catalog and support identities on a frozen checkout.

The controller supplies complete upstream release lists and sourced Ascend pairs.
This module does not fetch, build, or publish images. Pack calls ``promote`` only
after its collector has validated the frozen jobs, receipts, and manifests.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version

SUBSCRIPTIONS = (
    ("cuda", "vllm", ("",)),
    ("cuda", "sglang", ("",)),
    ("rocm", "vllm", ("",)),
    ("rocm", "sglang", ("",)),
    ("cann", "vllm", ("950", "a3", "910b", "310p")),
    ("cann", "sglang", ("a3", "910b")),
)
UPSTREAMS = {"vllm": "vllm-project/vllm", "sglang": "sgl-project/sglang"}
ASCEND = "vllm-project/vllm-ascend"
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


class DiscoveryError(ValueError):
    """An inspection source is missing or malformed."""


def version(value):
    if not isinstance(value, str) or not value.strip():
        msg = "version must be a nonempty string"
        raise DiscoveryError(msg)
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise DiscoveryError(str(exc)) from exc


def canonical_variant(backend, variant):
    if backend not in BACKENDS.values() or not isinstance(variant, str):
        msg = "unknown backend or variant"
        raise DiscoveryError(msg)
    value = variant.strip().lower()
    if backend == "cann" and value in CANN_ALIASES:
        return CANN_ALIASES[value]
    if backend != "cann" and value in {"", "-"}:
        return ""
    msg = f"unknown {backend} variant: {variant}"
    raise DiscoveryError(msg)


def _identity(backend, runtime, service, variant, engine, plugin=None):
    if service not in SERVICES:
        msg = f"unknown service: {service}"
        raise DiscoveryError(msg)
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
        raise DiscoveryError(msg)
    platforms = [p.strip() for p in value.split(",")]
    if (
        not platforms
        or len(set(platforms)) != len(platforms)
        or any(
            not re.fullmatch(r"linux/(amd64|arm64)(/v[0-9]+)?", p) for p in platforms
        )
    ):
        msg = "invalid or duplicate support platforms"
        raise DiscoveryError(msg)
    return platforms


def _cells(line):
    if not line.startswith("|") or not line.endswith("|"):
        msg = "malformed support table row"
        raise DiscoveryError(msg)
    return [cell.strip() for cell in line[1:-1].split("|")]


def _table(lines):
    if len(lines) < 2:
        msg = "missing support table header"
        raise DiscoveryError(msg)
    header = _cells(lines[0])
    separator = _cells(lines[1])
    if len(separator) != len(header) or any(
        not re.fullmatch(r":?-{3,}:?", s) for s in separator
    ):
        msg = "malformed support table separator"
        raise DiscoveryError(msg)
    rows = [_cells(line) for line in lines[2:]]
    if any(len(row) != len(header) for row in rows):
        msg = "support table column count differs"
        raise DiscoveryError(msg)
    return header, rows


def _explicit_records(text):
    if (
        text.count(START) != 1
        or text.count(END) != 1
        or text.index(START) > text.index(END)
    ):
        msg = "missing or duplicate support record markers"
        raise DiscoveryError(msg)
    body = text.split(START)[1].split(END)[0]
    header, rows = _table([line.strip() for line in body.splitlines() if line.strip()])
    if header != COLUMNS:
        msg = "unexpected support record columns"
        raise DiscoveryError(msg)
    records, seen = [], set()
    for cells in rows:
        backend, runtime, service, variant, engine, plugin, platforms, status = cells
        plugin = None if plugin == "-" else plugin
        if status not in {"prepared", "published"}:
            msg = "support status must be prepared or published"
            raise DiscoveryError(msg)
        if (backend == "cann" and service == "vllm") != (plugin is not None):
            msg = "CANN vLLM requires an actual plugin version; other rows use -"
            raise DiscoveryError(msg)
        record = _identity(backend, runtime, service, variant, engine, plugin)
        record.update(platforms=_platforms(platforms), status=status)
        key = (*_key(record), version(runtime), tuple(sorted(record["platforms"])))
        if key in seen:
            msg = "duplicate support identity"
            raise DiscoveryError(msg)
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
                raise DiscoveryError(msg)
            for service, cell in zip(services, cells[1:], strict=False):
                # Parse only version cells in known backend/service tables.
                clean = re.sub(r"<br\s*/?>|\*\*|~~", "", cell).strip()
                for token in clean.split(",") if clean else []:
                    match = re.fullmatch(r"\s*`([^`]+)`\s*(\(rc\))?\s*", token)
                    if match is None:
                        msg = "malformed historical engine cell"
                        raise DiscoveryError(msg)
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
        raise DiscoveryError(msg)
    return explicit + legacy


def _catalog_records(value):
    if not isinstance(value, list):
        msg = "catalog must be a list"
        raise DiscoveryError(msg)
    records = []
    for row in value:
        if not isinstance(row, dict):
            msg = "catalog row must be an object"
            raise DiscoveryError(msg)
        dependencies = row.get("dependencies", {})
        if not isinstance(dependencies, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not v
            for k, v in dependencies.items()
        ):
            msg = "malformed catalog dependencies"
            raise DiscoveryError(msg)
        if not isinstance(row["docker_image"], str) or not row["docker_image"]:
            msg = "missing catalog image"
            raise DiscoveryError(msg)
        record = _identity(
            row["backend"],
            row["backend_version"],
            row["service"],
            row["backend_variant"],
            row["service_version"],
            dependencies.get("vllm-ascend")
            if row["backend"] == "cann" and row["service"] == "vllm"
            else None,
        )
        record.update(platforms=_platforms(row["platform"]), status="published")
        records.append(record)
    return records


def _read_sources(repo):
    catalog = _catalog_records(
        json.loads((repo / "gpustack_runner/runner.py.json").read_text()),
    )
    readme = (repo / "README.md").read_text()
    if re.search(r"\]\((?:\./)?docs/supported-runners\.md(?:#[^)]*)?\)", readme):
        path = repo / "docs/supported-runners.md"
        if not path.resolve().is_relative_to(repo.resolve()):
            msg = "support document escapes the frozen checkout"
            raise DiscoveryError(msg)
        support = parse_support(path.read_text(), require_explicit=True)
    else:
        support = parse_support(readme)
    return {"catalog": catalog, "support": support}


def _releases(rows, *, plugin=False):
    if not isinstance(rows, list):
        msg = "upstream releases must be a complete list"
        raise DiscoveryError(msg)
    eligible = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("tag_name"), str)
            or any(type(row.get(key)) is not bool for key in ("draft", "prerelease"))
        ):
            msg = "malformed upstream release"
            raise DiscoveryError(msg)
        tag = row["tag_name"]
        if row["draft"] or not re.match(r"v?\d", tag):
            continue
        parsed = version(tag)
        if (
            parsed.is_devrelease
            or parsed.local
            or (not plugin and (parsed.is_prerelease or row["prerelease"]))
        ):
            continue
        eligible.add(parsed)
    return eligible


def _key(record):
    plugin = record["plugin_version"]
    return (
        record["backend"],
        record["service"],
        record["variant"],
        version(record["engine_version"]),
        version(plugin) if plugin is not None else None,
    )


def _candidate(service, backend, releases, pairs):
    engines = _releases(releases.get(UPSTREAMS[service]))
    versions = (
        _releases(releases.get(ASCEND), plugin=True)
        if backend == "cann" and service == "vllm"
        else engines
    )
    if not versions:
        return {"status": "blocked", "reason": "no eligible upstream release"}
    latest = max(versions)
    if backend != "cann" or service != "vllm":
        return {"engine_version": str(latest), "plugin_version": None}
    candidate = {"plugin_version": str(latest)}
    pair = pairs.get(str(latest))
    if (
        not isinstance(pair, dict)
        or not isinstance(pair.get("source"), str)
        or not pair["source"].startswith("https://")
    ):
        return {
            **candidate,
            "status": "blocked",
            "reason": "latest Ascend plugin has no sourced stable-engine pair",
        }
    engine = version(pair.get("engine_version"))
    if (
        engine not in engines
        or engine.is_prerelease
        or engine.is_devrelease
        or engine.local
    ):
        return {
            **candidate,
            "status": "blocked",
            "reason": "Ascend pair does not name a released stable engine",
        }
    return {**candidate, "engine_version": str(engine), "pair_source": pair["source"]}


def discover(repo: Path, releases: dict, ascend_pairs: dict) -> list[dict]:
    """
    Inspect six subscriptions; errors stay visible and never imply absence.

    ``repo`` must be the controller's frozen default-branch checkout, never an
    unmerged proposal. ``releases`` maps upstream repository names to complete
    GitHub release arrays. ``ascend_pairs`` maps normalized plugin versions to
    ``engine_version`` and an upstream HTTPS ``source`` from research.
    """
    results = []
    try:
        sources = _read_sources(Path(repo))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [
            {
                "subscription": f"{backend}/{service}",
                "backend": backend,
                "service": service,
                "status": "failed",
                "reason": f"detection source: {exc}",
            }
            for backend, service, _ in SUBSCRIPTIONS
        ]
    for backend, service, variants in SUBSCRIPTIONS:
        result = {
            "subscription": f"{backend}/{service}",
            "backend": backend,
            "service": service,
        }
        try:
            result.update(_candidate(service, backend, releases, ascend_pairs))
            if "status" not in result:
                result["variants"] = [
                    _match(result, variant, sources) for variant in variants
                ]
                result["status"] = (
                    "needs_update"
                    if any(v["status"] == "needs_update" for v in result["variants"])
                    else "unchanged"
                )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            result.update(status="failed", reason=f"upstream inspection: {exc}")
        results.append(result)
    return results


def _match(candidate, variant, sources):
    wanted = _key({**candidate, "variant": variant})
    exact, partial = [], []
    for source, records in sources.items():
        keys = [_key(row) for row in records]
        if wanted in keys:
            exact.append(source)
        if wanted[-1] is not None and (*wanted[:-1], None) in keys:
            partial.append(source)
    return {
        "variant": variant,
        "status": "unchanged" if exact else "needs_update",
        "sources": exact,
        "insufficient_identity": partial,
    }


def _installed_engine_matches(job, installed):
    measured, expected = version(installed), version(job["service_version"])
    if measured == expected:
        return True
    # Upstream vLLM setup.py adds accelerator build identifiers to releases.
    # Compare the public release without discarding rc/post/dev components.
    suffix = {"cuda": r"cu[0-9]+", "rocm": r"rocm[0-9]+"}.get(job["backend"])
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
        except DiscoveryError:
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
                and version(row["runtime"]) == version(record["runtime"])
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
            args.support.read_text(),
            json.loads(args.context.read_text())["matrix"]["build_jobs"],
            json.loads(args.dependencies.read_text()),
        )
        args.output.write_text(text)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"support promotion failed: {exc}\n")


if __name__ == "__main__":
    main()
