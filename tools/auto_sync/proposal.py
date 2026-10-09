"""
Validate complete release assessments as data, never as executable instructions.

Schema 1 is illustrated in tests/auto_sync/fixtures/proposals/ready.json. The
controller freezes identity before research. Only the final successful Qwen
result contains a proposal; process exit and intermediate messages are insufficient.

The analysis stage returns a separate handoff. Research completion is not
compatibility confirmation, so the handoff has no ready status; the trusted
validation job alone accepts a publishable proposal.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path, PurePosixPath

from tools.auto_sync.discovery import (
    SUBSCRIPTIONS,
    UPSTREAMS,
    canonical_variant,
    version,
)

STATUSES = {"ready", "unchanged", "blocked", "failed"}
ANALYSIS_STATUSES = {"analyzed", "blocked", "unchanged"}
ANALYSIS_FIELDS = {
    "subscription",
    "status",
    "reason",
    "engine_version",
    "plugin_version",
    "source_revision",
    "evidence",
    "findings",
    "patches",
    "unknowns",
}
IDENTITY_FIELDS = {
    "repository",
    "default_sha",
    "head_sha",
    "mode",
    "pr_number",
    "command_id",
    "command_digest",
}
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
PLATFORM = r"linux/(?:amd64|arm64)(?:/v[0-9]+)?"
REPOSITORY = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"


class ProposalError(ValueError):
    """The artifact cannot be used for publication."""


def require(predicate, message):
    if not predicate:
        raise ProposalError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(text):
    def invalid(value):
        msg = f"nonfinite JSON value: {value}"
        raise ProposalError(msg)

    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)
    except (ValueError, TypeError, RecursionError) as exc:
        msg = f"invalid JSON: {exc}"
        raise ProposalError(msg) from exc


def _text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"missing {label}")


def _strings(value, label, *, empty=False):
    require(isinstance(value, list) and (empty or bool(value)), f"invalid {label}")
    for item in value:
        _text(item, label)
    require(len(set(value)) == len(value), f"duplicate {label}")


def _sources(value):
    _strings(value, "evidence sources")
    require(
        all(re.fullmatch(r"https://[^\s/]+/[^\s]*", url) for url in value),
        "invalid evidence source URL",
    )


def _matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def validate_identity(identity):
    require(
        isinstance(identity, dict) and set(identity) == IDENTITY_FIELDS,
        "invalid identity fields",
    )
    require(_matches(identity["repository"], REPOSITORY), "invalid repository identity")
    for field in ("default_sha", "head_sha"):
        require(_matches(identity[field], SHA), f"invalid identity {field}")
    require(identity["mode"] in {"discover", "revise"}, "invalid identity mode")
    if identity["mode"] == "discover":
        require(
            identity["head_sha"] == identity["default_sha"],
            "discovery identity must use the default revision",
        )
        require(
            all(
                identity[k] is None
                for k in ("pr_number", "command_id", "command_digest")
            ),
            "discovery identity has a revision command",
        )
    else:
        require(
            type(identity["pr_number"]) is int and identity["pr_number"] > 0,
            "revision identity requires a PR number",
        )
        require(
            type(identity["command_id"]) is int and identity["command_id"] > 0,
            "revision identity requires a command ID",
        )
        require(
            _matches(identity["command_digest"], r"[0-9a-f]{64}"),
            "revision identity requires a command digest",
        )


def stream_lines(text: str) -> list[str]:
    """
    Frame NDJSON on its protocol LF boundary.

    A JSON string may carry a literal U+2028, U+2029, or U+0085; the pinned CLI
    emits only LF between events, so str.splitlines() would tear one event apart.
    """
    return text.split("\n")


def ordered_secrets(secrets) -> list[str]:
    """Match the longest secret first, including its JSON-escaped spelling."""
    return sorted(
        {
            value
            for secret in secrets
            if secret
            for value in (secret, json.dumps(secret)[1:-1])
        },
        key=len,
        reverse=True,
    )


def redact(value, ordered: list[str]):
    """
    Scrub secret text from parsed data without disturbing JSON scalar types.

    A nested JSON document inside a string field is redacted as structure, so a
    secret such as ``null`` or ``false`` cannot rewrite its scalar values into
    text and make the document unparsable.
    """
    if isinstance(value, str):
        nested = _nested_json(value)
        if nested is not None:
            return json.dumps(redact(nested, ordered))
        for secret in ordered:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {
            redact(key, ordered): redact(item, ordered) for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, ordered) for item in value]
    return value


def _nested_json(value: str):
    """Return a nested JSON document carried inside a string field, else None."""
    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        parsed = load_json(stripped)
    except ProposalError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def parse_agent_output(result) -> dict:
    """Extract schema data from T1's ProcessResult and the pinned Qwen event log."""
    require(
        result.returncode == 0 and not result.timed_out,
        "agent process failed or timed out",
    )
    events = (
        load_json(result.stdout)
        if result.stdout.lstrip().startswith("[")
        else [load_json(line) for line in stream_lines(result.stdout) if line.strip()]
    )
    require(
        isinstance(events, list) and bool(events),
        "Qwen output must contain events",
    )
    require(all(isinstance(event, dict) for event in events), "malformed Qwen event")
    final = events[-1]
    require(final.get("type") == "result", "Qwen final result is missing")
    require(
        sum(
            event.get("type") == "result" and event.get("parent_tool_use_id") is None
            for event in events
        )
        == 1,
        "ambiguous Qwen final result",
    )
    require(
        final.get("subtype") == "success" and final.get("is_error") is False,
        "Qwen final result failed",
    )
    data = load_json(final.get("result"))
    require(isinstance(data, dict), "proposal output must be an object")
    return data


def allowed_path(path, rows):
    """Only selected recipes, relevant patches, the matrix, and support prose."""
    require(_matches(path, r"[A-Za-z0-9_./-]+"), "unsafe patch path")
    parts = PurePosixPath(path).parts
    require(
        not path.startswith("/")
        and ".." not in parts
        and "." not in path.split("/")
        and "//" not in path,
        "escaping patch path",
    )
    if path in {
        "pack/matrix.yaml",
        "README.md",
        "docs/supported-runners.md",
        "docs/release-automation.md",
    }:
        return
    selected = {(row["backend"], row["service"]) for row in rows}
    if any(
        path == f"pack/{backend}/Dockerfile.{service}" for backend, service in selected
    ):
        return
    if (
        len(parts) >= 5
        and parts[0] == "pack"
        and parts[2] == "patches"
        and path.endswith(".patch")
    ):
        components = {service for backend, service in selected if backend == parts[1]}
        # Engine-related plugin and Omni patches belong to the same combination.
        if parts[3] in components or (
            "vllm" in components and parts[3] in {"vllm_ascend", "vllm_omni"}
        ):
            return
    msg = f"forbidden patch path: {path}"
    raise ProposalError(msg)


def patch_paths(patch, rows):
    """Accept ordinary text Git diffs; reject ambiguous headers and file modes."""
    require(isinstance(patch, str), "patch must be text")
    if not patch:
        return []
    paths = []
    current = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/([^\s]+) b/([^\s]+)", line)
            require(
                match is not None and match[1] == match[2],
                "unsafe or renamed patch path",
            )
            current = match[1]
            allowed_path(current, rows)
            require(current not in paths, "duplicate patch path")
            paths.append(current)
        elif line.startswith(("--- ", "+++ ")):
            require(current is not None, "patch path header precedes diff")
            expected = ("a/" if line.startswith("---") else "b/") + current
            require(line[4:] in {expected, "/dev/null"}, "patch path headers disagree")
        elif line.startswith(
            ("old mode ", "new mode ", "new file mode ", "deleted file mode "),
        ):
            require(line.rsplit(" ", 1)[-1] == "100644", "forbidden patch file mode")
        elif line.startswith("index "):
            fields = line.split()
            require(
                len(fields) in {2, 3} and (len(fields) == 2 or fields[2] == "100644"),
                "forbidden patch index mode",
            )
        elif line.startswith(
            (
                "GIT binary patch",
                "Binary files ",
                "rename ",
                "copy ",
                "similarity index ",
            ),
        ):
            msg = "binary, renamed, or copied patch paths are forbidden"
            raise ProposalError(msg)
        else:
            require(
                current is not None or not line.strip(),
                "patch has unframed content",
            )
    require(bool(paths), "patch has no allowed paths")
    return paths


def _patch_decision(patch, row):
    require(isinstance(patch, dict), "invalid patch disposition")
    required = {
        "path",
        "disposition",
        "reason",
        "versions",
        "platforms",
        "sources",
        "source_repository",
        "source_revision",
    }
    require(set(patch) == required, "invalid patch disposition fields")
    require(
        patch["disposition"] in {"retain", "adapt", "remove", "add"},
        "invalid patch disposition",
    )
    allowed_path(patch["path"], [row])
    require(patch["path"].endswith(".patch"), "disposition must name a patch")
    _text(patch["reason"], "patch reason")
    _strings(patch["versions"], "patch versions")
    for value in patch["versions"]:
        version(value)
    _strings(patch["platforms"], "patch platforms")
    require(
        row["platform"] in patch["platforms"]
        and all(_matches(p, PLATFORM) for p in patch["platforms"]),
        "invalid patch platforms",
    )
    _sources(patch["sources"])
    require(
        _matches(patch["source_repository"], REPOSITORY),
        "invalid patch source repository",
    )
    require(
        patch["source_revision"] is None or _matches(patch["source_revision"], SHA),
        "patch source must be an exact revision or unknown",
    )


def _row(row, ready, engine_prereleases):
    fields = {
        "backend",
        "service",
        "variant",
        "runtime",
        "old_engine_version",
        "engine_version",
        "plugin_version",
        "platform",
        "base_image",
        "manifest",
        "python",
        "torch",
        "packages",
        "patches",
        "conclusion",
        "sources",
        "checks",
        "deferred",
    }
    require(
        isinstance(row, dict) and set(row) == fields,
        "invalid compatibility row fields",
    )
    require(
        (row["backend"], row["service"]) in {(b, s) for b, s, _ in SUBSCRIPTIONS},
        "unsubscribed compatibility row",
    )
    row["variant"] = canonical_variant(row["backend"], row["variant"])
    engine = version(row["engine_version"])
    require(
        not (engine.is_devrelease or engine.local)
        and (
            not engine.is_prerelease
            or (row["backend"], row["service"], str(engine)) in engine_prereleases
        ),
        "engine must use the stable release policy",
    )
    for field in ("runtime", "old_engine_version", "python", "torch"):
        if row[field] is not None:
            version(row[field])
    plugin = row["plugin_version"]
    require(
        (row["backend"] == "cann" and row["service"] == "vllm") == (plugin is not None),
        "CANN vLLM requires an actual plugin version",
    )
    if plugin is not None:
        parsed = version(plugin)
        require(
            not parsed.is_devrelease and parsed.local is None,
            "invalid plugin release",
        )
    require(_matches(row["platform"], PLATFORM), "invalid compatibility platform")
    require(
        _matches(row["base_image"], r"[A-Za-z0-9_.:/@-]+"),
        "unsafe base image reference",
    )
    manifest = row["manifest"]
    if manifest is None:
        require(not ready, "ready row lacks manifest evidence")
    else:
        require(
            isinstance(manifest, dict)
            and set(manifest)
            == {"digest", "platform_digest", "platform", "config_platform", "sources"},
            "invalid manifest evidence",
        )
        require(
            all(_matches(manifest[k], DIGEST) for k in ("digest", "platform_digest")),
            "invalid manifest digest",
        )
        require(
            manifest["platform"] == manifest["config_platform"] == row["platform"],
            "manifest/configuration platform mismatch",
        )
        _sources(manifest["sources"])
    require(
        row["conclusion"] in {"upstream", "inference", "unresolved"},
        "invalid evidence classification",
    )
    require(
        not ready or row["conclusion"] != "unresolved",
        "unresolved compatibility cannot be ready",
    )
    _sources(row["sources"])
    _strings(row["checks"], "checks", empty=not ready)
    _strings(row["deferred"], "deferred runtime checks")
    require(isinstance(row["packages"], list), "invalid additional packages")
    names = []
    for package in row["packages"]:
        require(
            isinstance(package, dict)
            and set(package) == {"name", "version", "decision", "reason", "sources"},
            "invalid additional package choice",
        )
        require(
            _matches(package["name"], r"[A-Za-z0-9_.-]+"),
            "invalid additional package name",
        )
        require(
            package["decision"] in {"retain", "update", "disable", "source"},
            "invalid additional package decision",
        )
        if package["version"] is not None:
            if package["decision"] != "source" or not _matches(
                package["version"],
                r"[0-9a-f]{7,40}",
            ):
                version(package["version"])
        else:
            require(
                package["decision"] == "disable" or not ready,
                "ready additional package has unknown version",
            )
        _text(package["reason"], "additional package reason")
        _sources(package["sources"])
        names.append(package["name"].lower())
    require(len(names) == len(set(names)), "duplicate additional packages")
    require(isinstance(row["patches"], list), "invalid patch dispositions")
    for patch in row["patches"]:
        _patch_decision(patch, row)
    require(
        len({p["path"] for p in row["patches"]}) == len(row["patches"]),
        "duplicate patch dispositions",
    )


def _analysis_versions(candidate, selected):
    """An analysis may echo the discovered selection, never replace it."""
    for field in ("engine_version", "plugin_version"):
        value = candidate[field]
        claimed = selected.get(field)
        if value is None:
            require(
                claimed is None or candidate["status"] != "analyzed",
                f"analyzed candidate lacks {field}",
            )
            continue
        require(
            claimed is not None and version(value) == version(claimed),
            f"analysis {field} differs from the discovered candidate",
        )


def _analysis_revision(candidate, evidence, found):
    revision = candidate["source_revision"]
    if candidate["status"] == "analyzed":
        require(_matches(revision, SHA), "analyzed candidate lacks an exact revision")
    if revision is None:
        return
    require(_matches(revision, SHA), "analysis revision must be an exact commit")
    service = candidate["subscription"].split("/", 1)[1]
    selected = found[candidate["subscription"]]
    key = f"{UPSTREAMS[service]}@{selected['engine_version']}"
    record = evidence.get(key)
    require(
        record is not None and record.get("revision") == revision,
        "analysis revision differs from the acquired upstream source",
    )


def _analysis_evidence(candidate, evidence):
    entries = candidate["evidence"]
    require(isinstance(entries, list), "invalid analysis evidence")
    if candidate["status"] == "analyzed":
        require(bool(entries), "analyzed candidate lacks evidence")
    supplied, roots = set(), []
    for record in evidence.values():
        for key in ("path", "release_notes_path", "release_metadata_path"):
            value = record.get(key)
            if isinstance(value, str):
                supplied.add(value)
        if isinstance(record.get("path"), str):
            roots.append(Path(record["path"]))
    for item in entries:
        require(isinstance(item, str) and bool(item.strip()), "invalid evidence entry")
        if item in evidence or item in supplied:
            continue
        if re.fullmatch(r"https://[^\s/]+/[^\s]*", item):
            continue
        if _matches(item, r"[A-Za-z0-9_./-]+") and not item.startswith("/"):
            # A repository-relative reference the next session can resolve itself.
            require(".." not in PurePosixPath(item).parts, "escaping evidence path")
            continue
        path = Path(item)
        require(
            path.is_absolute()
            and ".." not in path.parts
            and any(path.is_relative_to(root) for root in roots),
            "analysis evidence outside the supplied sources",
        )


def validate_analysis(data, expected_identity, *, found, evidence):
    """
    Validate the analysis-stage handoff before a fresh proposal session starts.

    The handoff carries facts and evidence references for the discovered
    candidates. It cannot declare readiness, change the frozen identity or
    selection, or cite sources the controller never supplied.
    """
    try:
        require(
            isinstance(data, dict)
            and set(data) == {"schema_version", "identity", "candidates"},
            "invalid analysis fields",
        )
        require(
            type(data["schema_version"]) is int and data["schema_version"] == 1,
            "unsupported analysis schema",
        )
        require(
            data["identity"] == expected_identity,
            "analysis identity differs from frozen identity",
        )
        validate_identity(expected_identity)
        data = copy.deepcopy(data)
        selected = {c["subscription"]: c for c in found}
        seen = set()
        for candidate in data["candidates"]:
            require(
                isinstance(candidate, dict) and set(candidate) == ANALYSIS_FIELDS,
                "invalid analysis candidate fields",
            )
            name = candidate["subscription"]
            require(
                name in selected and name not in seen,
                "unknown or duplicate analysis subscription",
            )
            seen.add(name)
            status = candidate["status"]
            require(status in ANALYSIS_STATUSES, "invalid analysis status")
            _text(candidate["reason"], "analysis reason")
            _analysis_versions(candidate, selected[name])
            if selected[name]["status"] == "needs_update":
                require(
                    status != "unchanged",
                    "analysis cannot mark a required candidate unchanged",
                )
            else:
                require(
                    status == "unchanged",
                    "analysis cannot research an already settled candidate",
                )
                require(
                    candidate["engine_version"] is None
                    and candidate["plugin_version"] is None
                    and candidate["source_revision"] is None
                    and not candidate["evidence"]
                    and not candidate["unknowns"],
                    "unchanged analysis carries research claims",
                )
            if status == "blocked":
                _strings(candidate["unknowns"], "analysis unknowns")
            else:
                require(
                    isinstance(candidate["unknowns"], list)
                    and all(isinstance(u, str) for u in candidate["unknowns"]),
                    "invalid analysis unknowns",
                )
            if status == "analyzed":
                _text(candidate["findings"], "analysis findings")
                _text(candidate["patches"], "analysis patch review")
            else:
                require(
                    isinstance(candidate["findings"], str)
                    and isinstance(candidate["patches"], str),
                    "invalid analysis text fields",
                )
            _analysis_revision(candidate, evidence, selected)
            _analysis_evidence(candidate, evidence)
        require(
            seen == {f"{b}/{s}" for b, s, _ in SUBSCRIPTIONS},
            "incomplete analysis candidates",
        )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        if isinstance(exc, ProposalError):
            raise
        msg = f"malformed analysis: {exc}"
        raise ProposalError(msg) from exc
    else:
        return data


def validate_proposal(
    data: dict,
    expected_identity: dict,
    *,
    engine_prereleases: set | None = None,
) -> dict:
    """Return a normalized copy or fail closed before any candidate file is read."""
    try:
        require(
            isinstance(data, dict)
            and set(data) == {"schema_version", "identity", "candidates", "groups"},
            "invalid proposal fields",
        )
        require(
            type(data["schema_version"]) is int and data["schema_version"] == 1,
            "unsupported proposal schema",
        )
        require(
            data["identity"] == expected_identity,
            "proposal identity differs from frozen identity",
        )
        validate_identity(expected_identity)
        permission = engine_prereleases if engine_prereleases is not None else set()
        require(isinstance(permission, set), "invalid engine prerelease permission")
        require(
            not permission or expected_identity["mode"] == "revise",
            "prerelease permission requires an authorized revision",
        )
        for item in permission:
            require(
                isinstance(item, tuple)
                and len(item) == 3
                and item[0] in {"cuda", "rocm"}
                and item[1] in {"vllm", "sglang"},
                "invalid engine prerelease permission scope",
            )
            parsed = version(item[2])
            require(
                parsed.is_prerelease
                and not parsed.is_devrelease
                and not parsed.local
                and str(parsed) == item[2],
                "invalid exact engine prerelease permission",
            )
        data = copy.deepcopy(data)
        require(isinstance(data["groups"], list), "invalid compatibility groups")
        groups = {}
        manifests = {}
        platform_digests = {}
        for group in data["groups"]:
            require(
                isinstance(group, dict)
                and set(group)
                == {"id", "status", "reason", "depends_on", "report", "patch", "rows"},
                "invalid compatibility group fields",
            )
            require(
                _matches(group["id"], r"[A-Za-z0-9_-]+") and group["id"] not in groups,
                "invalid or duplicate group ID",
            )
            require(group["status"] in STATUSES, "invalid group status")
            for field in ("report", "reason"):
                _text(group[field], f"group {field}")
            _strings(group["depends_on"], "group dependencies", empty=True)
            require(
                isinstance(group["rows"], list) and bool(group["rows"]),
                "group lacks compatibility rows",
            )
            ready = group["status"] == "ready"
            for row in group["rows"]:
                _row(row, ready, permission)
                manifest = row["manifest"]
                if manifest is not None:
                    image = row["base_image"]
                    require(
                        image not in manifests
                        or manifests[image] == manifest["digest"],
                        "conflicting manifest evidence for the same image reference",
                    )
                    manifests[image] = manifest["digest"]
                    digest = manifest["platform_digest"]
                    require(
                        digest not in platform_digests
                        or platform_digests[digest] == row["platform"],
                        "manifest child digest has conflicting platform evidence",
                    )
                    platform_digests[digest] = row["platform"]
            keys = [
                (r["backend"], r["service"], r["variant"], r["runtime"], r["platform"])
                for r in group["rows"]
            ]
            require(len(set(keys)) == len(keys), "duplicate compatibility rows")
            require(not ready or bool(group["patch"]), "ready group lacks a patch")
            require(
                group["status"] != "unchanged" or not group["patch"],
                "unchanged group contains changes",
            )
            patch_paths(group["patch"], group["rows"])
            groups[group["id"]] = group
        remaining = set(groups)
        done = set()
        while remaining:
            available = {
                name for name in remaining if set(groups[name]["depends_on"]) <= done
            }
            require(bool(available), "unknown or cyclic group dependency")
            remaining -= available
            done |= available
        require(isinstance(data["candidates"], list), "invalid candidate assessments")
        subscriptions = {f"{b}/{s}" for b, s, _ in SUBSCRIPTIONS}
        seen, referenced = set(), set()
        for candidate in data["candidates"]:
            require(
                isinstance(candidate, dict)
                and set(candidate) == {"subscription", "status", "groups", "reason"},
                "invalid candidate fields",
            )
            name = candidate["subscription"]
            require(
                name in subscriptions and name not in seen,
                "unknown or duplicate subscription",
            )
            seen.add(name)
            require(candidate["status"] in STATUSES, "invalid candidate assessment")
            _text(candidate["reason"], "candidate reason")
            _strings(candidate["groups"], "candidate groups", empty=True)
            require(
                set(candidate["groups"]) <= groups.keys(),
                "candidate references an unknown group",
            )
            for group_id in candidate["groups"]:
                require(
                    any(
                        f"{r['backend']}/{r['service']}" == name
                        for r in groups[group_id]["rows"]
                    ),
                    "candidate references an unrelated group",
                )
            states = {groups[g]["status"] for g in candidate["groups"]}
            if states:
                assessed = next(
                    status
                    for status in ("ready", "failed", "blocked", "unchanged")
                    if status in states
                )
                require(
                    assessed == candidate["status"],
                    "candidate assessment disagrees with groups",
                )
            else:
                require(candidate["status"] != "ready", "ready candidate lacks a group")
            referenced.update(candidate["groups"])
        require(seen == subscriptions, "incomplete candidate assessments")
        require(referenced == groups.keys(), "unreferenced compatibility group")
        for group in groups.values():
            for row in group["rows"]:
                name = f"{row['backend']}/{row['service']}"
                require(
                    any(
                        c["subscription"] == name and group["id"] in c["groups"]
                        for c in data["candidates"]
                    ),
                    "group row lacks a candidate assessment",
                )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        if isinstance(exc, ProposalError):
            raise
        msg = f"malformed proposal: {exc}"
        raise ProposalError(msg) from exc
    else:
        return data
