"""
Credential-free checks apply candidate data in disposable exact-source clones.

No candidate tests, hooks, agent settings, Docker builds, or matrix shell scripts
are executed. Manifest evidence is checked for consistency, not reclassified as
measured runtime compatibility. Missing upstream source remains unverified.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from tools.auto_sync.discovery import (
    BACKENDS,
    SERVICES,
    canonical_variant,
    parse_support,
    version,
)
from tools.auto_sync.proposal import (
    ProposalError,
    allowed_path,
    load_json,
    patch_paths,
    require,
    validate_proposal,
)

# A package choice is keyed by its canonical name, but the installed
# distribution can carry a backend-qualified name for the same recipe pin.
_PACKAGE_ALIASES = {
    "mooncake-transfer-engine": "mooncake",
    "mooncake-transfer-engine-rocm": "mooncake",
}


def _run(argv, env, *, cwd=None, text=None):
    try:
        result = subprocess.run(  # noqa: S603 - argv is trusted; candidate content goes to stdin.
            argv,
            cwd=cwd,
            env=env,
            input=text,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = f"static check failed: {exc}"
        raise ProposalError(msg) from exc
    require(result.returncode == 0, f"static check failed: {result.stderr.strip()}")
    return result.stdout


def _git(env, repo, *args, text=None):
    return _run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.attributesFile=/dev/null",
            "-C",
            str(repo),
            *args,
        ],
        env,
        text=text,
    )


def _clone(repo, sha, target, env):
    require(Path(repo).is_dir(), "source repository is unavailable")
    actual = _git(env, repo, "rev-parse", "--verify", sha + "^{commit}").strip()
    require(actual == sha, "source revision is not the exact declared commit")
    _run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "clone",
            "--quiet",
            "--no-checkout",
            "--no-hardlinks",
            "--no-recurse-submodules",
            "--template=",
            "--",
            str(Path(repo).resolve()),
            str(target),
        ],
        env,
    )
    _git(env, target, "checkout", "--quiet", "--detach", sha)


def _safe_file(root, path):
    current = root
    for part in Path(path).parts:
        current /= part
        require(not current.is_symlink(), f"symlink in candidate path: {path}")
    require(
        current.resolve().is_relative_to(root.resolve()),
        f"escaping candidate path: {path}",
    )
    return current


def _matrix(repo, env):
    path = _safe_file(repo, "pack/matrix.yaml")
    # Go yq's fixed identity expression reads YAML, without shell or env expansion.
    value = load_json(
        _run(["yq", "eval", "--output-format", "json", ".", str(path)], env),
    )
    require(
        isinstance(value, dict)
        and set(value) == {"rules"}
        and isinstance(value["rules"], list),
        "invalid matrix rules",
    )
    for rule in value["rules"]:
        require(
            isinstance(rule, dict)
            and {"backend", "services"} <= rule.keys()
            and rule.keys() <= {"backend", "services", "platforms", "args"},
            "invalid matrix rule fields",
        )
        require(rule["backend"] in BACKENDS.values(), "unknown matrix backend")
        services = rule["services"]
        require(
            isinstance(services, list)
            and services
            and all(s in SERVICES for s in services)
            and len(set(services)) == len(services),
            "invalid matrix services",
        )
        platforms = rule.get("platforms", ["linux/amd64", "linux/arm64"])
        require(
            isinstance(platforms, list)
            and platforms
            and len(set(platforms)) == len(platforms)
            and all(
                isinstance(p, str)
                and re.fullmatch(r"linux/(amd64|arm64)(/v[0-9]+)?", p)
                for p in platforms
            ),
            "invalid matrix platforms",
        )
        args = rule.get("args", [])
        require(isinstance(args, list), "invalid matrix arguments")
        names = []
        for argument in args:
            require(
                isinstance(argument, str)
                and re.fullmatch(r"[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:+@,=-]*", argument),
                "unsafe matrix argument",
            )
            names.append(argument.split("=", 1)[0])
        require(len(names) == len(set(names)), "duplicate matrix arguments")
    return value["rules"]


def _check_matrix_scope(before, after, rows):
    selected = {(r["backend"], r["service"]) for r in rows}

    def unrelated(rules):
        return [
            dict(rule, services=[service])
            for rule in rules
            for service in rule["services"]
            if (rule["backend"], service) not in selected
        ]

    require(
        unrelated(before) == unrelated(after),
        "matrix changes an unselected combination",
    )


def _arguments(repo, rule, service):
    path = _safe_file(repo, f"pack/{rule['backend']}/Dockerfile.{service}")
    require(path.is_file(), "selected recipe is missing")
    defaults = {}
    for line in path.read_text().splitlines():
        if line.startswith("FROM "):
            break
        match = re.fullmatch(r"ARG ([A-Z][A-Z0-9_]*)=(.*)", line)
        if match:
            defaults[match[1]] = match[2].strip('"')
    defaults.update(argument.split("=", 1) for argument in rule.get("args", []))

    def expand(name, stack=()):
        require(
            name not in stack and name in defaults,
            "unknown or cyclic Dockerfile argument",
        )
        raw = defaults[name]
        return re.sub(
            r"\$\{([A-Z][A-Z0-9_]*)\}",
            lambda m: expand(m[1], (*stack, name)),
            raw,
        )

    # This expands only named ARG references as strings. It never runs shell expressions.
    return {name: expand(name) for name in defaults}


def _image(repo, backend, service, args):
    stages = {}
    for line in (
        _safe_file(repo, f"pack/{backend}/Dockerfile.{service}")
        .read_text()
        .splitlines()
    ):
        if not line.upper().startswith("FROM "):
            continue
        match = re.fullmatch(r"FROM\s+(\S+)\s+AS\s+(\S+)\s*", line, re.IGNORECASE)
        require(
            match is not None,
            "unsupported FROM expression; image evidence cannot be bound",
        )
        reference = re.sub(
            r"\$\{([A-Z][A-Z0-9_]*)\}",
            lambda m: args.get(m[1], m[0]),
            match[1],
        )
        require(
            "$" not in reference and match[2] not in stages,
            "unresolved or duplicate image stage",
        )
        stages[match[2]] = stages.get(reference, reference)
    require(service in stages, "selected service stage is missing")
    return stages[service]


def _configurations(repo, rules):
    result = {}
    for rule in rules:
        if rule["backend"] not in {"cuda", "rocm", "cann"}:
            continue
        for service in rule["services"]:
            if service not in {"vllm", "sglang"}:
                continue
            args = _arguments(repo, rule, service)
            backend = rule["backend"]
            variant = canonical_variant(
                backend,
                args.get("CANN_ARCHS", "") if backend == "cann" else "",
            )
            runtime = str(version(args.get(f"{backend.upper()}_VERSION")))
            for platform in rule.get("platforms", ["linux/amd64", "linux/arm64"]):
                key = (backend, service, variant, runtime, platform)
                require(key not in result, "duplicate effective matrix combination")
                result[key] = args
    return result


def _row_key(row):
    return (
        row["backend"],
        row["service"],
        row["variant"],
        str(version(row["runtime"])),
        row["platform"],
    )


def _changed_configurations(before, after, rows, paths):
    touched = {
        (r["backend"], r["service"])
        for r in rows
        if f"pack/{r['backend']}/Dockerfile.{r['service']}" in paths
        or any(p.startswith(f"pack/{r['backend']}/patches/") for p in paths)
    }
    changed = {
        key
        for key, args in after.items()
        if before.get(key) != args or key[:2] in touched
    }
    require(
        changed <= {_row_key(row) for row in rows},
        "changed matrix combination lacks compatibility evidence",
    )
    return changed


def _check_rows(repo, rules, rows, baseline, ascend_pairs):
    for row in rows:
        matching = []
        for rule in rules:
            if (
                rule["backend"] != row["backend"]
                or row["service"] not in rule["services"]
            ):
                continue
            args = _arguments(repo, rule, row["service"])
            backend, service = row["backend"].upper(), row["service"].upper()
            variant = canonical_variant(
                row["backend"],
                args.get("CANN_ARCHS", "") if row["backend"] == "cann" else "",
            )
            runtime = args.get(f"{backend}_VERSION")
            if (
                variant == row["variant"]
                and runtime is not None
                and version(runtime) == version(row["runtime"])
            ):
                matching.append((rule, args))
        require(
            bool(matching),
            "compatibility row has no matching matrix runtime/variant",
        )
        for rule, args in matching:
            require(
                row["platform"]
                in rule.get("platforms", ["linux/amd64", "linux/arm64"]),
                "compatibility platform is absent from the matrix",
            )
            service = row["service"].upper()
            require(
                version(args.get(f"{service}_VERSION"))
                == version(row["engine_version"]),
                "compatibility engine differs from the effective matrix pin",
            )
            image = _image(repo, row["backend"], row["service"], args)
            require(
                image == row["base_image"],
                "base image evidence differs from the effective recipe",
            )
            if row["backend"] == "cann" and row["service"] == "vllm":
                pair = ascend_pairs.get(str(version(row["plugin_version"])))
                require(
                    isinstance(pair, dict)
                    and isinstance(pair.get("source"), str)
                    and pair["source"].startswith("https://"),
                    "Ascend plugin lacks controller-supplied upstream pairing evidence",
                )
                require(
                    version(pair.get("engine_version"))
                    == version(row["engine_version"]),
                    "Ascend plugin and engine differ from the upstream pairing evidence",
                )
            if "@sha256:" in image:
                require(
                    image.split("@", 1)[1] == row["manifest"]["digest"],
                    "pinned image and manifest digest disagree",
                )
            for field, name in (
                ("python", "PYTHON_VERSION"),
                ("torch", f"{service}_TORCH_VERSION"),
            ):
                if row[field] is not None:
                    require(
                        name in args and version(args[name]) == version(row[field]),
                        f"compatibility {field} differs from the effective recipe",
                    )
            packages = {}
            for p in row["packages"]:
                key = _PACKAGE_ALIASES.get(p["name"].lower(), p["name"].lower())
                require(key not in packages, "duplicate additional packages")
                packages[key] = p
            if any(
                Path(patch["path"]).parts[3] == "vllm_omni"
                and patch["disposition"] != "remove"
                and patch["source_revision"] is not None
                for patch in row["patches"]
            ):
                require(
                    bool(args.get(f"{service}_OMNI_COMMIT")),
                    "verified Omni patch source lacks an effective recipe pin",
                )
            for package, suffix in (
                ("lmcache", "LMCACHE_VERSION"),
                ("mooncake", "MOONCAKE_VERSION"),
                ("lmcache-ascend", "LMCACHE_ASCEND_VERSION"),
                ("lmcache-ascend", "LMCACHE_ASCEND_COMMIT"),
                ("vllm-omni", "OMNI_COMMIT"),
                ("diffusers", "DIFFUSERS_VERSION"),
            ):
                key = f"{service}_{suffix}"
                if key not in args:
                    continue
                require(
                    package in packages,
                    f"additional package choice is missing: {package}",
                )
                choice = packages[package]
                if choice["decision"] == "disable":
                    require(
                        args[key] == "",
                        "disabled additional package remains enabled",
                    )
                else:
                    require(
                        args[key] == choice["version"],
                        "additional package differs from the effective recipe pin",
                    )
        previous = baseline.get(_row_key(row))
        predecessors = (
            [previous]
            if previous is not None
            else [
                args
                for key, args in baseline.items()
                if key[:3] == _row_key(row)[:3] and key[4] == row["platform"]
            ]
        )
        if predecessors:
            require(
                row["old_engine_version"] is not None
                and version(row["old_engine_version"])
                in {
                    version(args[f"{row['service'].upper()}_VERSION"])
                    for args in predecessors
                },
                "old engine report differs from the frozen head",
            )
        else:
            require(
                row["old_engine_version"] is None,
                "new combination has no prior engine version",
            )
        # Every selected platform of this exact combination needs its own evidence.
        expected = {
            platform
            for rule, _ in matching
            for platform in rule.get("platforms", ["linux/amd64", "linux/arm64"])
        }
        reported = {
            r["platform"]
            for r in rows
            if all(
                r[k] == row[k]
                for k in (
                    "backend",
                    "service",
                    "variant",
                    "runtime",
                    "engine_version",
                    "base_image",
                )
            )
        }
        require(
            expected <= reported,
            "compatibility rows omit selected platform evidence",
        )


def _support_key(row):
    runtime = version(row["runtime"])
    return (
        row["backend"],
        row["service"],
        row["variant"],
        version(".".join(map(str, runtime.release[:2]))),
        version(row["engine_version"]),
        version(row["plugin_version"]) if row["plugin_version"] else None,
    )


def _check_support(before, after, rows, changed, protected):
    previous = parse_support(before, require_explicit=True)
    records = parse_support(after, require_explicit=True)
    immutable = [r for r in previous if r["status"] != "prepared" or r in protected]
    require(
        all(r in records for r in immutable),
        "candidate support removes previously accepted support metadata",
    )
    for record in records:
        if record in previous:
            continue
        require(
            record["status"] == "prepared",
            "candidate support cannot fabricate published metadata",
        )
        require(
            record["runtime"] == str(_support_key(record)[3]),
            "new support runtime line must match the catalog major.minor version",
        )
        platforms = {
            r["platform"] for r in rows if _support_key(r) == _support_key(record)
        }
        require(
            set(record["platforms"]) == platforms,
            "prepared record differs from checked configuration and platforms",
        )
    scopes = {tuple(_support_key(r)[:4]) for r in rows}
    require(
        all(r in records or tuple(_support_key(r)[:4]) in scopes for r in previous),
        "candidate removes unrelated proposal support",
    )
    for row in rows:
        if _row_key(row) in changed:
            require(
                any(
                    _support_key(r) == _support_key(row)
                    and row["platform"] in r["platforms"]
                    for r in records
                ),
                "changed configuration lacks a matching prepared support record",
            )


def _source_patch_checks(repo, group, sources, scratch, env):
    outcomes = []
    checked = set()
    for row in group["rows"]:
        stacks = {}
        for decision in sorted(row["patches"], key=lambda item: item["path"]):
            key = decision["source_repository"], decision["source_revision"]
            stacks.setdefault(key, []).append(decision)
        for (upstream, revision), decisions in stacks.items():
            identity = (
                upstream,
                revision,
                tuple((d["path"], d["disposition"]) for d in decisions),
            )
            if identity in checked:
                continue
            checked.add(identity)
            work = None
            source = sources.get(upstream)
            if source is not None and revision is not None:
                try:
                    _git(env, source, "cat-file", "-e", revision + "^{commit}")
                except ProposalError:
                    pass
                else:
                    work = scratch / f"source-{len(checked)}"
                    _clone(source, revision, work, env)
            for decision in decisions:
                patch = _safe_file(repo, decision["path"])
                outcome = {
                    "path": decision["path"],
                    "source_repository": upstream,
                    "source_revision": revision,
                    "status": "unverified",
                    "reason": "Exact upstream source is unavailable.",
                }
                if decision["disposition"] == "remove":
                    require(not patch.exists(), "removed patch still exists")
                    outcome.update(
                        status="passed",
                        reason="Removed patch needs no application check.",
                    )
                else:
                    require(
                        patch.is_file(),
                        f"declared patch is missing: {decision['path']}",
                    )
                    if work is not None:
                        content = patch.read_text()
                        _git(
                            env,
                            work,
                            "apply",
                            "--check",
                            "--whitespace=error",
                            "-",
                            text=content,
                        )
                        _git(
                            env,
                            work,
                            "apply",
                            "--whitespace=error",
                            "-",
                            text=content,
                        )
                        outcome.update(
                            status="passed",
                            reason="Applied in recipe order against the exact source revision.",
                        )
                outcomes.append(outcome)
    return outcomes


def _check_patch_dispositions(before, after, paths, group):
    decisions = {d["path"]: d for row in group["rows"] for d in row["patches"]}
    for path in paths:
        if path.endswith(".patch"):
            require(path in decisions, f"changed patch lacks a disposition: {path}")
            disposition = decisions[path]["disposition"]
            existed = _safe_file(before, path).exists()
            exists = _safe_file(after, path).exists()
            require(
                (disposition == "add" and not existed and exists)
                or (disposition == "adapt" and existed and exists)
                or (disposition == "remove" and existed and not exists),
                "patch changes disagree with disposition",
            )
    # Every patch of an affected component needs a decision, including retained patches.
    for row in group["rows"]:
        root = before / "pack" / row["backend"] / "patches"
        components = {row["service"]}
        if row["service"] == "vllm":
            components |= {"vllm_ascend", "vllm_omni"}
        for component in components:
            directory = _safe_file(before, str((root / component).relative_to(before)))
            for patch in directory.rglob("*.patch"):
                path = str(patch.relative_to(before))
                _safe_file(before, path)
                require(
                    path in decisions,
                    f"affected existing patch lacks a disposition: {path}",
                )


def _lmcache_versions(repo, rules):
    versions = set()
    for backend in ("cuda", "rocm"):
        for service in ("vllm", "sglang"):
            path = _safe_file(repo, f"pack/{backend}/Dockerfile.{service}")
            if path.is_file():
                versions.update(
                    re.findall(
                        r"^ARG (?:VLLM|SGLANG)_LMCACHE_VERSION=([^\s]+)$",
                        path.read_text(),
                        re.MULTILINE,
                    ),
                )
    for rule in rules:
        if rule["backend"] in {"cuda", "rocm"}:
            for service in rule["services"]:
                if service in {"vllm", "sglang"}:
                    value = _arguments(repo, rule, service).get(
                        f"{service.upper()}_LMCACHE_VERSION",
                    )
                    if value:
                        versions.add(value)
    return versions


def _check_group(base, work, group, sources, scratch, env, protected, ascend_pairs):
    previous_tree = _git(env, work, "write-tree").strip()
    paths = patch_paths(group["patch"], group["rows"])
    for path in paths:
        allowed_path(path, group["rows"])
        _safe_file(work, path)
    before_matrix = _matrix(work, env)
    before_configs = _configurations(work, before_matrix)
    before_support = _safe_file(work, "docs/support-records.md").read_text()
    before_lmcache = _lmcache_versions(work, before_matrix)
    _git(env, work, "apply", "--check", "--whitespace=error", "-", text=group["patch"])
    _git(env, work, "apply", "--whitespace=error", "-", text=group["patch"])
    # New files are untracked until staged in this disposable clone.
    _git(env, work, "add", "--", *paths)
    actual = _git(
        env,
        work,
        "diff",
        "--cached",
        previous_tree,
        "--name-only",
        "-z",
    ).split("\0")
    require(
        set(filter(None, actual)) == set(paths),
        "patch paths disagree with applied changes",
    )
    for path in paths:
        _safe_file(work, path)
    after_matrix = _matrix(work, env)
    _check_matrix_scope(before_matrix, after_matrix, group["rows"])
    changed = _changed_configurations(
        before_configs,
        _configurations(work, after_matrix),
        group["rows"],
        paths,
    )
    _check_rows(
        work,
        after_matrix,
        group["rows"],
        _configurations(base, _matrix(base, env)),
        ascend_pairs,
    )
    require(
        re.search(
            r"\]\((?:\./)?docs/supported-runners\.md(?:#[^)]*)?\)",
            _safe_file(work, "README.md").read_text(),
        ),
        "README lost its authoritative support link",
    )
    _check_support(
        before_support,
        _safe_file(work, "docs/support-records.md").read_text(),
        group["rows"],
        changed,
        protected,
    )
    after_lmcache = _lmcache_versions(work, after_matrix)
    require(
        after_lmcache == before_lmcache or len(after_lmcache) <= 1,
        "LMCache cross-image protocol pins diverge",
    )
    _check_patch_dispositions(base, work, paths, group)
    return {
        "status": "passed",
        "paths": paths,
        "patches": _source_patch_checks(work, group, sources, scratch, env),
        "checks": [
            "Exact-head git apply",
            "Allowed paths and regular files",
            "Trusted static data validation",
        ],
        "runtime": "unverified",
    }


def report_digest(artifact):
    """Bind all candidate outcomes and reports to the frozen identity and patch."""
    content = {
        key: artifact[key]
        for key in (
            "schema_version",
            "identity",
            "candidates",
            "groups",
            "patch_digest",
        )
    }
    return hashlib.sha256(
        json.dumps(
            content,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode(),
    ).hexdigest()


def verify_artifact(
    artifact: dict,
    expected_identity: dict,
    *,
    engine_prereleases: set | None = None,
) -> dict:
    """
    Check transport integrity and return proposal data for clean-runner rechecks.

    Digests bind the patch and reports; they do not authenticate agent assertions.
    Call validate_candidate again before granting publication credentials.
    """
    try:
        fields = {
            "schema_version",
            "identity",
            "candidates",
            "groups",
            "patch",
            "patch_digest",
            "report_digest",
        }
        require(
            isinstance(artifact, dict) and set(artifact) == fields,
            "invalid checked artifact fields",
        )
        require(
            artifact["identity"] == expected_identity,
            "checked artifact identity differs from frozen identity",
        )
        require(
            hashlib.sha256(artifact["patch"].encode()).hexdigest()
            == artifact["patch_digest"],
            "checked artifact patch digest mismatch",
        )
        require(
            report_digest(artifact) == artifact["report_digest"],
            "checked artifact report digest mismatch",
        )
        require(
            artifact["patch"]
            == "".join(
                g["patch"] for g in artifact["groups"] if g["status"] == "ready"
            ),
            "checked artifact contains an unapproved patch",
        )
        raw = copy.deepcopy(
            {
                key: artifact[key]
                for key in ("schema_version", "identity", "candidates", "groups")
            },
        )
        for group in raw["groups"]:
            validation = group.pop("validation")
            require(isinstance(validation, dict), "group validation is missing")
            if group["status"] == "ready":
                require(
                    validation.get("status") == "passed"
                    and validation.get("runtime") == "unverified",
                    "ready group lacks trusted static checks",
                )
        return validate_proposal(
            raw,
            expected_identity,
            engine_prereleases=engine_prereleases,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        if isinstance(exc, ProposalError):
            raise
        msg = f"malformed checked artifact: {exc}"
        raise ProposalError(msg) from exc


def validate_candidate(
    repo: Path,
    proposal: dict,
    expected_identity: dict,
    *,
    sources: dict | None = None,
    ascend_pairs: dict | None = None,
    engine_prereleases: set | None = None,
) -> dict:
    """
    Return checked data and only accepted groups' patch; malformed data raises.

    ``repo`` is a clean trusted local object store containing default and head
    commits. ``sources`` maps upstream repository names to local exact-source
    object stores. It never authorizes a checkout's moving HEAD as evidence.
    ``ascend_pairs`` uses discovery's sourced plugin-to-stable-engine mapping.
    The controller supplies it independently of proposal data. Neither an image
    tag nor a README RC marker establishes the installed plugin version.
    Individual static failures remain in their group's report and assessment.
    Publication must verify identity and recompute checks on its clean runner.
    """
    data = validate_proposal(
        proposal,
        expected_identity,
        engine_prereleases=engine_prereleases,
    )
    with tempfile.TemporaryDirectory(prefix="runner-proposal-") as temporary:
        scratch = Path(temporary)
        home = scratch / "home"
        home.mkdir()
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home),
            "TMPDIR": str(scratch),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/usr/bin/false",
            "SSH_ASKPASS": "/usr/bin/false",
        }
        for tool in ("git", "yq"):
            require(
                shutil.which(tool, path=env["PATH"]) is not None,
                f"trusted check tool is missing: {tool}",
            )
        # Verify both revisions even when discovery and proposal head are equal.
        for sha in {expected_identity["default_sha"], expected_identity["head_sha"]}:
            try:
                actual = _git(
                    env,
                    repo,
                    "rev-parse",
                    "--verify",
                    sha + "^{commit}",
                ).strip()
            except ProposalError as exc:
                msg = "frozen source revision is unavailable"
                raise ProposalError(msg) from exc
            require(actual == sha, "frozen source revision is not exact")
        base = scratch / "base"
        _clone(repo, expected_identity["head_sha"], base, env)
        protected = parse_support(
            _git(
                env,
                repo,
                "show",
                expected_identity["default_sha"] + ":docs/support-records.md",
            ),
            require_explicit=True,
        )
        groups = {group["id"]: group for group in data["groups"]}
        pending = set(groups)
        accepted = []
        checked_groups = []
        finished = set()
        while pending:
            available = [
                g
                for g in data["groups"]
                if g["id"] in pending and set(g["depends_on"]) <= finished
            ]
            for group in available:
                checked_groups.append(group)
                pending.remove(group["id"])
                finished.add(group["id"])
                if group["status"] != "ready":
                    group["validation"] = {
                        "status": "skipped",
                        "reason": group["reason"],
                    }
                    continue
                if any(
                    groups[name]["status"] != "ready" for name in group["depends_on"]
                ):
                    group.update(
                        status="blocked",
                        validation={
                            "status": "skipped",
                            "reason": "Required compatibility group was rejected.",
                        },
                    )
                    continue
                work = scratch / f"group-{group['id']}"
                _clone(repo, expected_identity["head_sha"], work, env)
                for previous in accepted:
                    _git(env, work, "apply", "-", text=previous["patch"])
                # Commit-free staging makes comparison relative to preceding accepted groups.
                _git(env, work, "add", "-A")
                try:
                    group["validation"] = _check_group(
                        base,
                        work,
                        group,
                        sources or {},
                        scratch / group["id"],
                        env,
                        protected,
                        ascend_pairs or {},
                    )
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    group.update(
                        status="failed",
                        validation={"status": "failed", "error": str(exc)},
                    )
                else:
                    accepted.append(group)
        data["groups"] = checked_groups
        for candidate in data["candidates"]:
            states = {groups[name]["status"] for name in candidate["groups"]}
            if states:
                candidate["status"] = next(
                    status
                    for status in ("ready", "failed", "blocked", "unchanged")
                    if status in states
                )
        data["patch"] = "".join(group["patch"] for group in accepted)
        data["patch_digest"] = hashlib.sha256(data["patch"].encode()).hexdigest()
        data["report_digest"] = report_digest(data)
    return data
