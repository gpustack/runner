"""Validate an auto-sync candidate directory deterministically offline."""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml
from packaging.version import InvalidVersion, Version
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

SUBSCRIPTIONS = (
    "cuda/vllm",
    "cuda/sglang",
    "rocm/vllm",
    "rocm/sglang",
    "cann/vllm",
    "cann/sglang",
)
UPSTREAM_IDS = {"vllm", "sglang", "vllm-ascend"}
BACKENDS = {"cann", "corex", "cuda", "dtk", "hggc", "maca", "musa", "rocm"}
SERVICES = {"vllm", "sglang", "mindie", "voxbox"}
STATUSES = {"ready", "unchanged", "blocked", "failed"}
DECISIONS = {"retain", "update", "disable", "source"}
DISPOSITIONS = {"retain", "adapt", "remove", "add"}
PLATFORMS = {"linux/amd64", "linux/arm64"}
BLOCKED_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104 - denylisted host literal, not a socket bind.
    "::1",
    "[::1]",
}
BLOCKED_HOST_SUFFIXES = (".example.com", ".invalid", ".local", ".test")
PACK_RUN_URL_RE = re.compile(
    r"^https://github\.com/gpustack/runner/actions/runs/[0-9]+(?:/job/[0-9]+)?$",
)
COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
COMPANION_ARG_TO_PACKAGE = {
    "VLLM_LMCACHE_VERSION": "lmcache",
    "SGLANG_LMCACHE_VERSION": "lmcache",
    "VLLM_MOONCAKE_VERSION": "mooncake",
    "SGLANG_MOONCAKE_VERSION": "mooncake",
    "VLLM_LMCACHE_ASCEND_VERSION": "lmcache-ascend",
    "VLLM_OMNI_VERSION": "vllm-omni",
    "SGLANG_DIFFUSERS_VERSION": "diffusers",
}
CANONICAL_PACKAGES = {
    "lmcache",
    "mooncake",
    "lmcache-ascend",
    "vllm-omni",
    "diffusers",
    "vllm-ascend",
}
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
CONTROL_ROOT = ".auto-sync"
PROPOSAL_REL_PATH = ".auto-sync/proposal.json"
DIGESTS_LOCK_REL_PATH = ".auto-sync/digests.lock.json"
CONTROL_PLANE_PROTECTED_PATHS = (
    ".auto-sync/taskpack.yaml",
    ".auto-sync/taskpack.yml",
    ".auto-sync/taskpack.json",
    ".auto-sync/digests.lock.json",
    ".auto-sync/checks",
    ".auto-sync/policies",
)
ALLOWED_CONTROL_ROOT_ENTRIES = {
    "checks",
    "digests.lock.json",
    "instructions.md",
    "memory",
    "policies",
    "proposal.json",
    "taskpack.json",
    "taskpack.yaml",
    "taskpack.yml",
}
MEMORY_ENTRY_HEADER_FENCE = "---"
FORBIDDEN_MEMORY_NAME_PATTERNS = (
    re.compile(r"\.sqlite(?:-wal|-shm)?$", re.IGNORECASE),
    re.compile(r"^run\.json$", re.IGNORECASE),
    re.compile(r"^privateSession", re.IGNORECASE),
    re.compile(r"checkpoint", re.IGNORECASE),
)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
BUILTIN_PROTECTED_PATHS = (
    ".github",
    ".claude",
    ".codex",
    ".agents",
    ".loopwright/policies",
    "AGENTS.md",
    "CLAUDE.md",
    CONTROL_ROOT,
)
SYNCED_PACK_BACKENDS = ("cuda", "rocm", "cann")
BACKEND_WRITABLE_PATCH_PREFIXES = {
    "cuda": ("pack/cuda/patches/",),
    "rocm": ("pack/rocm/patches/",),
    "cann": (
        "pack/cann/patches/vllm/",
        "pack/cann/patches/vllm_ascend/",
        "pack/cann/patches/vllm_omni/",
        "pack/cann/patches/sglang/",
    ),
}
SUPPORT_START = "<!-- runner-support-records:start -->"
SUPPORT_END = "<!-- runner-support-records:end -->"
SUPPORT_COLUMNS = [
    "Backend",
    "Runtime",
    "Service",
    "Variant",
    "Engine",
    "Plugin",
    "Platforms",
    "Status",
]
REQUIRED_DOCKERFILE_ARGS = {
    ("cuda", "vllm"): (
        "PYTHON_VERSION",
        "CUDA_VERSION",
        "VLLM_VERSION",
        "VLLM_TORCH_VERSION",
        "VLLM_BASE_IMAGE",
    ),
    ("cuda", "sglang"): (
        "PYTHON_VERSION",
        "CUDA_VERSION",
        "SGLANG_VERSION",
        "SGLANG_TORCH_VERSION",
        "SGLANG_BASE_IMAGE",
    ),
    ("rocm", "vllm"): (
        "PYTHON_VERSION",
        "ROCM_VERSION",
        "VLLM_VERSION",
        "VLLM_TORCH_VERSION",
        "VLLM_BASE_IMAGE",
    ),
    ("rocm", "sglang"): (
        "PYTHON_VERSION",
        "ROCM_VERSION",
        "SGLANG_VERSION",
        "SGLANG_TORCH_VERSION",
        "SGLANG_BASE_IMAGE",
    ),
    ("cann", "vllm"): (
        "PYTHON_VERSION",
        "CANN_VERSION",
        "VLLM_VERSION",
        "VLLM_TORCH_VERSION",
        "CANN_BASE_IMAGE",
    ),
    ("cann", "sglang"): (
        "PYTHON_VERSION",
        "CANN_VERSION",
        "SGLANG_VERSION",
        "SGLANG_TORCH_VERSION",
        "SGLANG_BASE_IMAGE",
    ),
}


class ValidationError(ValueError):
    """Candidate verification failure."""


def _require(predicate: bool, message: str) -> None:
    if not predicate:
        raise ValidationError(message)


def _safe_path(root: Path, rel: str) -> Path:
    _require(isinstance(rel, str) and bool(rel), "path must be a non-empty string")
    _require(
        not rel.startswith("/") and "\\" not in rel,
        f"invalid relative path: {rel}",
    )
    posix = PurePosixPath(rel)
    _require(
        ".." not in posix.parts and "." not in rel.split("/") and "//" not in rel,
        f"unsafe path: {rel}",
    )
    current = root
    for part in posix.parts:
        current = current / part
        _require(
            not current.is_symlink(),
            f"symlink not allowed in candidate path: {rel}",
        )
    resolved_root = root.resolve()
    resolved = current.resolve()
    _require(
        resolved == resolved_root or resolved.is_relative_to(resolved_root),
        f"escaping path: {rel}",
    )
    return current


def _read_regular_text(root: Path, rel: str) -> str:
    path = _safe_path(root, rel)
    _require(path.is_file(), f"missing required regular file: {rel}")
    return path.read_text(encoding="utf-8")


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_strict_json(text: str, label: str) -> object:
    def _reject_constant(value: str) -> object:
        msg = f"{label} contains non-finite JSON constant: {value}"
        raise ValidationError(msg)

    try:
        return json.loads(
            text,
            object_pairs_hook=_json_pairs,
            parse_constant=_reject_constant,
        )
    except ValidationError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        msg = f"{label} invalid JSON: {exc}"
        raise ValidationError(msg) from exc


def _check_yaml_duplicates(node: Node, seen: set[int], label: str) -> None:
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        keys: set[object] = set()
        for key, value in node.value:
            if isinstance(key, ScalarNode):
                _require(
                    key.value not in keys,
                    f"{label} duplicate YAML mapping key: {key.value!r}",
                )
                keys.add(key.value)
            _check_yaml_duplicates(key, seen, label)
            _check_yaml_duplicates(value, seen, label)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            _check_yaml_duplicates(item, seen, label)


def _load_strict_yaml(text: str, label: str) -> object:
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        if node is not None:
            _check_yaml_duplicates(node, set(), label)
        return yaml.safe_load(text)
    except ValidationError:
        raise
    except yaml.YAMLError as exc:
        msg = f"{label} invalid YAML: {exc}"
        raise ValidationError(msg) from exc


def _parse_bare_pep440(value: object, label: str) -> Version:
    _require(
        isinstance(value, str) and bool(value.strip()),
        f"{label} must be a non-empty version string",
    )
    text = value.strip()
    _require(text == value, f"{label} must not have surrounding whitespace: {value!r}")
    _require(
        bool(re.match(r"^[0-9]", text)),
        f"{label} must be a bare PEP 440 version without prefix: {value!r}",
    )
    try:
        return Version(text)
    except InvalidVersion as exc:
        msg = f"{label} invalid PEP 440 version {value!r}: {exc}"
        raise ValidationError(msg) from exc


def _validate_https_urls(
    urls: object,
    label: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    _require(isinstance(urls, list), f"{label} must be a list of https:// URLs")
    if not allow_empty:
        _require(bool(urls), f"{label} must not be empty")
    for url in urls:
        _require(
            isinstance(url, str) and bool(url),
            f"{label} entries must be non-empty strings",
        )
        _require(
            not any(ch.isspace() for ch in url),
            f"{label} URL contains whitespace: {url!r}",
        )
        parts = urlsplit(url)
        _require(
            parts.scheme == "https"
            and bool(parts.hostname)
            and not parts.username
            and not parts.password,
            f"{label} must contain bare https:// URLs: {url!r}",
        )
        host = (parts.hostname or "").lower()
        _require(
            host not in BLOCKED_HOSTS
            and not any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES),
            f"{label} URL uses disallowed placeholder or loopback host: {url!r}",
        )
        _require(
            parts.path not in {"", "/"},
            f"{label} URL must include a non-root path: {url!r}",
        )
    return list(urls)


WINDOWS_RESERVED_RE = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)",
    re.IGNORECASE,
)
SCOPE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._*?-]+$")


def _path_covered_by(candidate: str, prefix: str) -> bool:
    clean_prefix = prefix.rstrip("/")
    return candidate == clean_prefix or candidate.startswith(f"{clean_prefix}/")


def _path_covered_by_ci(candidate: str, prefix: str) -> bool:
    return _path_covered_by(candidate.lower(), prefix.lower())


def _normalize_scope_rel_path(rel: object, label: str) -> str:
    _require(
        isinstance(rel, str) and bool(rel.strip()),
        f"{label} must be a non-empty relative path",
    )
    _require(
        not rel.startswith("/") and not rel.endswith("/") and "\\" not in rel,
        f"{label} must be a normalized relative POSIX path: {rel!r}",
    )
    posix = PurePosixPath(rel)
    _require(
        ".." not in posix.parts and "." not in rel.split("/") and "//" not in rel,
        f"{label} contains unsafe segments: {rel!r}",
    )
    return rel


def _normalize_scope_pattern(raw: object, label: str) -> str:
    _require(
        isinstance(raw, str) and bool(raw.strip()) and len(raw) <= 1024,
        f"{label} must be a non-empty scope pattern",
    )
    _require(
        raw != "**",
        f"{label} unbounded '**' scope pattern is not allowed",
    )
    _require(
        not raw.startswith("/") and not raw.endswith("/") and "\\" not in raw,
        f"{label} must be a normalized relative POSIX scope pattern: {raw!r}",
    )
    recursive = raw.endswith("/**")
    body = raw[:-3] if recursive else raw
    _require(
        bool(body) and "//" not in raw,
        f"{label} invalid scope pattern: {raw!r}",
    )
    _require(
        not any(ch in body for ch in "{}[]!") and "**" not in body,
        f"{label} unsupported glob syntax in scope pattern: {raw!r}",
    )
    segments = body.split("/")
    _require(len(segments) <= 32, f"{label} exceeds segment limit: {raw!r}")
    wildcards = 0
    for seg in segments:
        _require(
            bool(seg)
            and seg not in {".", ".."}
            and not seg.endswith(".")
            and not WINDOWS_RESERVED_RE.match(seg)
            and bool(SCOPE_SEGMENT_RE.fullmatch(seg)),
            f"{label} contains unsafe segment {seg!r} in {raw!r}",
        )
        wildcards += seg.count("*") + seg.count("?")
        _require(wildcards <= 16, f"{label} exceeds wildcard limit: {raw!r}")
    return raw


def _match_segment(pattern: str, text: str) -> bool:
    pi = 0
    ti = 0
    star_pi = -1
    star_ti = 0
    while ti < len(text):
        if pi < len(pattern) and (pattern[pi] == "?" or pattern[pi] == text[ti]):
            pi += 1
            ti += 1
        elif pi < len(pattern) and pattern[pi] == "*":
            star_pi = pi
            pi += 1
            star_ti = ti
        elif star_pi != -1:
            pi = star_pi + 1
            star_ti += 1
            ti = star_ti
        else:
            return False
    while pi < len(pattern) and pattern[pi] == "*":
        pi += 1
    return pi == len(pattern)


def _matches_scope_pattern(
    pattern: str,
    rel_path: str,
    *,
    case_insensitive: bool = False,
) -> bool:
    pat = pattern.lower() if case_insensitive else pattern
    name = rel_path.lower() if case_insensitive else rel_path
    if pat == "**":
        return True
    if pat.endswith("/**"):
        prefix = pat[:-3]
        if "*" not in prefix and "?" not in prefix:
            return name == prefix or name.startswith(f"{prefix}/")
        pat_segs = prefix.split("/")
        name_segs = name.split("/")
        if len(name_segs) < len(pat_segs):
            return False
        return all(_match_segment(ps, name_segs[i]) for i, ps in enumerate(pat_segs))
    if "*" not in pat and "?" not in pat:
        return pat == name
    pat_segs = pat.split("/")
    name_segs = name.split("/")
    if len(name_segs) != len(pat_segs):
        return False
    return all(_match_segment(ps, name_segs[i]) for i, ps in enumerate(pat_segs))


def _as_protected_subtree_pattern(entry: str) -> str:
    if entry == "**" or entry.endswith("/**") or "*" in entry or "?" in entry:
        return entry
    return f"{entry}/**"


def _segments_may_intersect(seg_a: str, seg_b: str) -> bool:
    m, n = len(seg_a), len(seg_b)
    memo: dict[tuple[int, int], bool] = {}

    def solve(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == m and j == n:
            res = True
        elif i < m and seg_a[i] == "*":
            res = solve(i + 1, j) or (j < n and solve(i, j + 1))
        elif j < n and seg_b[j] == "*":
            res = solve(i, j + 1) or (i < m and solve(i + 1, j))
        elif (
            i < m
            and j < n
            and (seg_a[i] == "?" or seg_b[j] == "?" or seg_a[i] == seg_b[j])
        ):
            res = solve(i + 1, j + 1)
        else:
            res = False
        memo[key] = res
        return res

    return solve(0, 0)


def _segment_subset_of(seg_a: str, seg_b: str) -> bool:
    m, n = len(seg_a), len(seg_b)
    memo: dict[tuple[int, int], bool] = {}

    def solve(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == m and j == n:
            res = True
        elif j < n and seg_b[j] == "*":
            res = solve(i, j + 1) or (i < m and solve(i + 1, j))
        elif (
            i < m
            and j < n
            and seg_a[i] != "*"
            and (seg_b[j] == "?" or seg_a[i] == seg_b[j])
        ):
            res = solve(i + 1, j + 1)
        else:
            res = False
        memo[key] = res
        return res

    return solve(0, 0)


def _split_scope_pattern(
    pattern: str,
    *,
    case_insensitive: bool = False,
) -> tuple[list[str], bool]:
    norm = pattern.lower() if case_insensitive else pattern
    if norm == "**":
        return [], True
    recursive = norm.endswith("/**")
    body = norm[:-3] if recursive else norm
    return body.split("/"), recursive


def _scope_patterns_may_intersect(
    pat_a: str,
    pat_b: str,
    *,
    case_insensitive: bool = False,
) -> bool:
    segs_a, rec_a = _split_scope_pattern(pat_a, case_insensitive=case_insensitive)
    segs_b, rec_b = _split_scope_pattern(pat_b, case_insensitive=case_insensitive)
    for k in range(max(len(segs_a), len(segs_b))):
        if k >= len(segs_a):
            return rec_a
        if k >= len(segs_b):
            return rec_b
        if not _segments_may_intersect(segs_a[k], segs_b[k]):
            return False
    return True


def _scope_pattern_subset_of(
    sub: str,
    sup: str,
    *,
    case_insensitive: bool = False,
) -> bool:
    segs_a, rec_a = _split_scope_pattern(sub, case_insensitive=case_insensitive)
    segs_b, rec_b = _split_scope_pattern(sup, case_insensitive=case_insensitive)
    if rec_b:
        if len(segs_a) < len(segs_b):
            return False
        return all(_segment_subset_of(segs_a[k], segs_b[k]) for k in range(len(segs_b)))
    if rec_a or len(segs_a) != len(segs_b):
        return False
    return all(_segment_subset_of(segs_a[k], segs_b[k]) for k in range(len(segs_b)))


def _is_bare_literal_scope_pattern(pattern: str) -> bool:
    return not pattern.endswith("/**") and "*" not in pattern and "?" not in pattern


def classify_scope_path(
    rel_path: str,
    writable: tuple[str, ...],
    protected: tuple[str, ...],
    *,
    proposal_path: str | None = None,
) -> str:
    """Classify a repo-relative path using Taskpack 2.0 Protected-Wins-Over-Writable glob rules."""
    norm = _normalize_scope_rel_path(rel_path, "candidate path")
    if proposal_path is not None:
        norm_proposal = _normalize_scope_rel_path(proposal_path, "spec.proposal.path")
        if (
            norm == norm_proposal
            and norm_proposal.startswith(f"{CONTROL_ROOT}/")
            and norm_proposal in writable
        ):
            if any(
                p_path != CONTROL_ROOT
                and _matches_scope_pattern(
                    _as_protected_subtree_pattern(p_path),
                    norm,
                    case_insensitive=True,
                )
                for p_path in protected
            ):
                return "protected"
            return "writable"
    if any(
        _matches_scope_pattern(
            _as_protected_subtree_pattern(p_path),
            norm,
            case_insensitive=True,
        )
        for p_path in protected
    ):
        return "protected"
    if any(_matches_scope_pattern(w_path, norm) for w_path in writable):
        return "writable"
    return "outside_writable"


def _load_scope_and_proposal_path(
    root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str]:
    """Load writable, effective-protected, manifest-protected scope patterns, and proposal.path."""
    raw = _load_strict_yaml(
        _read_regular_text(root, ".auto-sync/taskpack.yaml"),
        ".auto-sync/taskpack.yaml",
    )
    _require(
        isinstance(raw, dict) and isinstance(raw.get("spec"), dict),
        ".auto-sync/taskpack.yaml missing spec mapping",
    )
    spec = raw["spec"]
    scope = spec.get("scope")
    _require(isinstance(scope, dict), ".auto-sync/taskpack.yaml missing spec.scope")
    raw_writable = scope.get("writable")
    raw_protected = scope.get("protected", [])
    _require(
        isinstance(raw_writable, list) and bool(raw_writable),
        ".auto-sync/taskpack.yaml spec.scope.writable must be a non-empty list",
    )
    _require(
        isinstance(raw_protected, list),
        ".auto-sync/taskpack.yaml spec.scope.protected must be a list",
    )
    proposal_cfg = spec.get("proposal")
    _require(
        isinstance(proposal_cfg, dict) and isinstance(proposal_cfg.get("path"), str),
        ".auto-sync/taskpack.yaml missing spec.proposal.path",
    )
    proposal_path = _normalize_scope_rel_path(
        proposal_cfg["path"],
        "spec.proposal.path",
    )

    writable = tuple(
        _normalize_scope_pattern(item, "spec.scope.writable entry")
        for item in raw_writable
    )
    manifest_protected = tuple(
        _normalize_scope_pattern(item, "spec.scope.protected entry")
        for item in raw_protected
    )

    mandatory_protected: list[str] = [
        item for item in BUILTIN_PROTECTED_PATHS if item != CONTROL_ROOT
    ]
    mandatory_protected.extend(CONTROL_PLANE_PROTECTED_PATHS)

    exec_cfg = spec.get("execution")
    if isinstance(exec_cfg, dict):
        digests_cfg = exec_cfg.get("digests")
        if isinstance(digests_cfg, dict) and isinstance(
            digests_cfg.get("lockfile"),
            str,
        ):
            mandatory_protected.append(
                _normalize_scope_rel_path(
                    digests_cfg["lockfile"],
                    "spec.execution.digests.lockfile",
                ),
            )

    instructions = spec.get("instructions")
    if isinstance(instructions, str):
        mandatory_protected.append(
            _normalize_scope_rel_path(instructions, "spec.instructions entry"),
        )
    elif isinstance(instructions, list):
        for item in instructions:
            mandatory_protected.append(
                _normalize_scope_rel_path(item, "spec.instructions entry"),
            )

    memory_cfg = spec.get("memory")
    if isinstance(memory_cfg, dict) and isinstance(memory_cfg.get("directory"), str):
        mandatory_protected.append(
            _normalize_scope_rel_path(
                memory_cfg["directory"],
                "spec.memory.directory",
            ),
        )

    verification = spec.get("verification")
    if isinstance(verification, dict) and isinstance(
        verification.get("localChecks"),
        list,
    ):
        for check in verification["localChecks"]:
            if isinstance(check, dict) and check.get("implementation") == "command.v1":
                params = check.get("parameters")
                if isinstance(params, dict) and isinstance(params.get("script"), str):
                    mandatory_protected.append(
                        _normalize_scope_rel_path(
                            params["script"],
                            "command.v1 script",
                        ),
                    )

    mandatory_protected_set = set(mandatory_protected)
    non_carvable_protected = [*mandatory_protected, *manifest_protected]
    effective_protected = tuple(
        dict.fromkeys([*BUILTIN_PROTECTED_PATHS, *non_carvable_protected]),
    )

    proposal_in_control_root = _path_covered_by_ci(proposal_path, CONTROL_ROOT)
    if proposal_in_control_root:
        _require(
            proposal_path.startswith(f"{CONTROL_ROOT}/")
            and proposal_path != CONTROL_ROOT,
            f"spec.proposal.path must name a file inside {CONTROL_ROOT}, not the directory itself",
        )
        for p_path in dict.fromkeys(non_carvable_protected):
            _require(
                not _scope_patterns_may_intersect(
                    proposal_path,
                    _as_protected_subtree_pattern(p_path),
                    case_insensitive=True,
                ),
                f"spec.proposal.path {proposal_path!r} overlaps protected path {p_path!r}",
            )
        _require(
            proposal_path in writable,
            f"control-root spec.proposal.path {proposal_path!r} requires an exact entry in spec.scope.writable",
        )
        _safe_path(root, proposal_path)

    for w_path in writable:
        is_carved_proposal = proposal_in_control_root and w_path == proposal_path
        for p_path in effective_protected:
            if is_carved_proposal and p_path == CONTROL_ROOT:
                continue
            p_subtree = _as_protected_subtree_pattern(p_path)
            _require(
                not _scope_pattern_subset_of(w_path, p_subtree, case_insensitive=True),
                f"writable path {w_path!r} lives inside protected path {p_path!r}",
            )
            if p_path in mandatory_protected_set or (
                p_path == CONTROL_ROOT and not is_carved_proposal
            ):
                _require(
                    not _scope_patterns_may_intersect(
                        w_path,
                        p_subtree,
                        case_insensitive=True,
                    ),
                    f"writable path {w_path!r} encompasses built-in protected path {p_path!r}",
                )
        for builtin_path in BUILTIN_PROTECTED_PATHS:
            if is_carved_proposal and builtin_path == CONTROL_ROOT:
                continue
            _require(
                not _scope_patterns_may_intersect(
                    w_path,
                    _as_protected_subtree_pattern(builtin_path),
                    case_insensitive=True,
                ),
                f"writable path {w_path!r} encompasses built-in protected path {builtin_path!r}",
            )
        if not is_carved_proposal and _is_bare_literal_scope_pattern(w_path):
            w_target = _safe_path(root, w_path)
            _require(
                not w_target.is_dir(),
                f"directory writable path {w_path!r} must use explicit '{w_path}/**' glob",
            )

    if not proposal_in_control_root:
        _require(
            classify_scope_path(
                proposal_path,
                writable,
                effective_protected,
                proposal_path=proposal_path,
            )
            == "writable",
            f"spec.proposal.path {proposal_path!r} must resolve inside writable scope",
        )

    for p_path in manifest_protected:
        if p_path.endswith("/**") and "*" not in p_path[:-3] and "?" not in p_path[:-3]:
            dir_rel = p_path[:-3]
            target = _safe_path(root, dir_rel)
            _require(
                target.is_dir(),
                f"protected directory missing from candidate: {p_path}",
            )
        elif _is_bare_literal_scope_pattern(p_path):
            target = _safe_path(root, p_path)
            _require(
                target.exists(),
                f"protected path missing from candidate: {p_path}",
            )
            _require(
                not target.is_dir(),
                f"directory protected path {p_path!r} must use explicit '{p_path}/**' glob",
            )
        else:
            p_subtree = _as_protected_subtree_pattern(p_path)
            matched_any = False
            for entry in sorted(root.rglob("*")):
                if (
                    ".git" in entry.parts
                    or "__pycache__" in entry.parts
                    or entry.name == ".DS_Store"
                ):
                    continue
                rel_entry = entry.relative_to(root).as_posix()
                if _matches_scope_pattern(p_subtree, rel_entry):
                    _safe_path(root, rel_entry)
                    matched_any = True
            _require(
                matched_any,
                f"protected glob matched no files in candidate: {p_path}",
            )
    return writable, effective_protected, manifest_protected, proposal_path


def load_effective_scope(
    root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Load writable, effective-protected, and manifest-protected scope prefixes from taskpack.yaml."""
    writable, effective_protected, manifest_protected, _ = (
        _load_scope_and_proposal_path(
            root,
        )
    )
    return writable, effective_protected, manifest_protected


def _resolve_base_snapshot_dir() -> Path | None:
    raw_base = os.environ.get("LOOPWRIGHT_BASE_DIR", "").strip()
    if not raw_base:
        return None
    base_path = Path(raw_base)
    _require(
        not base_path.is_symlink() and base_path.is_dir(),
        f"LOOPWRIGHT_BASE_DIR must be a non-symlink directory: {raw_base!r}",
    )
    return base_path.resolve()


def _collect_regular_tree_files(tree_root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(
        tree_root,
        topdown=True,
        followlinks=False,
    ):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        cur_dir = Path(dirpath)
        for dname in dirnames:
            dpath = cur_dir / dname
            rel_d = dpath.relative_to(tree_root).as_posix()
            _require(
                not dpath.is_symlink(),
                f"symlink not allowed in workspace tree: {rel_d}",
            )
        for fname in filenames:
            if fname == ".DS_Store":
                continue
            fpath = cur_dir / fname
            rel_f = fpath.relative_to(tree_root).as_posix()
            if rel_f == ".git":
                continue
            _require(
                not fpath.is_symlink() and fpath.is_file(),
                f"non-regular or symlink entry in workspace tree: {rel_f}",
            )
            files[rel_f] = fpath
    return files


def _validate_base_dir_scope(
    root: Path,
    base_dir: Path,
    writable: tuple[str, ...],
    protected: tuple[str, ...],
    *,
    proposal_path: str | None = None,
) -> None:
    filecmp.clear_cache()
    cand_files = _collect_regular_tree_files(root)
    base_files = _collect_regular_tree_files(base_dir)
    changed_paths: set[str] = set()
    for rel_path in sorted(set(cand_files) | set(base_files)):
        cand_f = cand_files.get(rel_path)
        base_f = base_files.get(rel_path)
        if cand_f is None or base_f is None:
            changed_paths.add(rel_path)
            continue
        if cand_f.stat().st_size != base_f.stat().st_size or not filecmp.cmp(
            cand_f,
            base_f,
            shallow=False,
        ):
            changed_paths.add(rel_path)

    for rel_path in sorted(changed_paths):
        verdict = classify_scope_path(
            rel_path,
            writable,
            protected,
            proposal_path=proposal_path,
        )
        _require(
            verdict != "protected",
            f"modified path is protected: {rel_path}",
        )
        _require(
            verdict == "writable",
            f"modified path is outside writable scope: {rel_path}",
        )


def _validate_git_scope(
    root: Path,
    writable: tuple[str, ...],
    protected: tuple[str, ...],
    *,
    proposal_path: str | None = None,
) -> None:
    if not (root / ".git").exists():
        base_dir = _resolve_base_snapshot_dir()
        if base_dir is not None:
            _validate_base_dir_scope(
                root,
                base_dir,
                writable,
                protected,
                proposal_path=proposal_path,
            )
        return
    git_bin = shutil.which("git")
    if git_bin is None:
        return

    changed_paths: set[str] = set()
    status_res = subprocess.run(  # noqa: S603 - fixed read-only git status on candidate root.
        [
            git_bin,
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    _require(
        status_res.returncode == 0,
        f"git status failed in candidate workspace: {status_res.stderr.strip()}",
    )
    tokens = status_res.stdout.split("\0")
    idx = 0
    while idx < len(tokens):
        entry = tokens[idx]
        idx += 1
        if not entry:
            continue
        status_xy = entry[:2]
        rel_path = entry[3:]
        if rel_path:
            changed_paths.add(rel_path.rstrip("/"))
        if status_xy[:1] in {"R", "C"} and idx < len(tokens) and tokens[idx]:
            changed_paths.add(tokens[idx].rstrip("/"))
            idx += 1

    diff_res = subprocess.run(  # noqa: S603 - fixed read-only git diff on candidate root.
        [git_bin, "-C", str(root), "diff", "--name-only", "-z", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if diff_res.returncode == 0:
        for item in diff_res.stdout.split("\0"):
            if item:
                changed_paths.add(item.rstrip("/"))

    for rel_path in sorted(changed_paths):
        if PurePosixPath(rel_path).name == ".DS_Store":
            continue
        verdict = classify_scope_path(
            rel_path,
            writable,
            protected,
            proposal_path=proposal_path,
        )
        _require(
            verdict != "protected",
            f"modified path is protected: {rel_path}",
        )
        _require(
            verdict == "writable",
            f"modified path is outside writable scope: {rel_path}",
        )


def _is_forbidden_memory_filename(name: str) -> bool:
    return any(pattern.search(name) for pattern in FORBIDDEN_MEMORY_NAME_PATTERNS)


def _require_non_hardlinked_regular_file(path: Path, label: str) -> None:
    _require(not path.is_symlink(), f"symbolic link not allowed: {label}")
    st = path.lstat()
    _require(
        stat.S_ISREG(st.st_mode) and st.st_nlink == 1,
        f"{label} must be a non-hardlinked regular file",
    )


def _validate_memory_store(root: Path) -> None:
    memory_root = root / ".auto-sync" / "memory"
    if not memory_root.exists() and not memory_root.is_symlink():
        return
    _require(
        not memory_root.is_symlink() and memory_root.is_dir(),
        ".auto-sync/memory must be a non-symlink directory",
    )

    for child in sorted(memory_root.iterdir(), key=lambda p: p.name):
        _require(
            not child.is_symlink(),
            f"symbolic links are not allowed under .auto-sync/memory: {child.name}",
        )
        _require(
            not _is_forbidden_memory_filename(child.name),
            f"forbidden file in .auto-sync/memory: {child.name}",
        )
        if child.name in {".gitkeep", ".DS_Store"}:
            _require_non_hardlinked_regular_file(
                child,
                f".auto-sync/memory/{child.name}",
            )
            continue
        _require(
            child.name == "auto-sync",
            f"unexpected entry under .auto-sync/memory: {child.name}",
        )

    taskpack_dir = memory_root / "auto-sync"
    if not taskpack_dir.exists() and not taskpack_dir.is_symlink():
        return
    _require(
        not taskpack_dir.is_symlink() and taskpack_dir.is_dir(),
        ".auto-sync/memory/auto-sync must be a non-symlink directory",
    )

    for item in sorted(taskpack_dir.iterdir(), key=lambda p: p.name):
        _require(
            not item.is_symlink(),
            f"symbolic links are not allowed under .auto-sync/memory/auto-sync: {item.name}",
        )
        _require(
            not _is_forbidden_memory_filename(item.name)
            and item.name != ".cas.lock"
            and ".tmp-" not in item.name,
            f"forbidden or transient file in .auto-sync/memory/auto-sync: {item.name}",
        )
        _require(
            item.name in {"index.json", "entries"},
            f"unexpected entry in .auto-sync/memory/auto-sync: {item.name}",
        )

    index_path = taskpack_dir / "index.json"
    entries_dir = taskpack_dir / "entries"
    if not index_path.exists():
        if entries_dir.exists():
            _require(
                not entries_dir.is_symlink() and entries_dir.is_dir(),
                ".auto-sync/memory/auto-sync/entries must be a directory",
            )
            _require(
                not any(entries_dir.iterdir()),
                ".auto-sync/memory/auto-sync/entries cannot contain files without index.json",
            )
        return

    _require_non_hardlinked_regular_file(
        index_path,
        ".auto-sync/memory/auto-sync/index.json",
    )
    _require(
        entries_dir.exists() and not entries_dir.is_symlink() and entries_dir.is_dir(),
        ".auto-sync/memory/auto-sync/entries directory is required when index.json exists",
    )

    index_data = _load_strict_json(
        index_path.read_text(encoding="utf-8"),
        ".auto-sync/memory/auto-sync/index.json",
    )
    _require(
        isinstance(index_data, dict),
        ".auto-sync/memory/auto-sync/index.json must be a JSON object",
    )
    _require(
        index_data.get("version") == 1
        and not isinstance(index_data.get("version"), bool),
        ".auto-sync/memory/auto-sync/index.json version must be 1",
    )
    _require(
        index_data.get("taskpack") == "auto-sync",
        ".auto-sync/memory/auto-sync/index.json taskpack must be 'auto-sync'",
    )
    repo_slug = index_data.get("repository")
    _require(
        isinstance(repo_slug, str) and bool(repo_slug.strip()),
        ".auto-sync/memory/auto-sync/index.json repository must be non-empty",
    )
    raw_entries = index_data.get("entries")
    raw_retired = index_data.get("retired")
    store_digest = index_data.get("storeDigest")
    _require(
        isinstance(raw_entries, list) and isinstance(raw_retired, list),
        ".auto-sync/memory/auto-sync/index.json entries and retired must be lists",
    )
    _require(
        isinstance(store_digest, dict)
        and store_digest.get("algorithm") == "sha256"
        and isinstance(store_digest.get("hex"), str)
        and bool(SHA256_HEX_RE.fullmatch(store_digest["hex"])),
        ".auto-sync/memory/auto-sync/index.json storeDigest must be a sha256 digest object",
    )

    expected_ids: set[str] = set()
    for row in raw_entries:
        _require(
            isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and bool(row["id"].strip()),
            "memory index entry must be an object with non-empty id",
        )
        expected_ids.add(row["id"])
    for retired_row in raw_retired:
        _require(
            isinstance(retired_row, dict)
            and isinstance(retired_row.get("entry"), dict),
            "memory retired row must contain an entry object",
        )
        retired_id = retired_row["entry"].get("id")
        _require(
            isinstance(retired_id, str) and bool(retired_id.strip()),
            "memory retired entry must have a non-empty id",
        )
        expected_ids.add(retired_id)

    observed_ids: set[str] = set()
    fence_open = f"{MEMORY_ENTRY_HEADER_FENCE}\n"
    fence_close = f"\n{MEMORY_ENTRY_HEADER_FENCE}\n"
    for entry_file in sorted(entries_dir.iterdir(), key=lambda p: p.name):
        label = f".auto-sync/memory/auto-sync/entries/{entry_file.name}"
        _require_non_hardlinked_regular_file(entry_file, label)
        _require(
            not _is_forbidden_memory_filename(entry_file.name)
            and ".tmp-" not in entry_file.name,
            f"forbidden or staging file in memory entries: {entry_file.name}",
        )
        _require(
            entry_file.name.endswith(".md"),
            f"unexpected non-markdown file in memory entries: {entry_file.name}",
        )
        entry_id = entry_file.name[: -len(".md")]
        text = entry_file.read_text(encoding="utf-8")
        _require(
            text.startswith(fence_open),
            f"memory entry missing JSON front-matter fence: {entry_file.name}",
        )
        closing = text.find(fence_close, len(fence_open))
        _require(
            closing > len(fence_open),
            f"memory entry missing closing front-matter fence: {entry_file.name}",
        )
        header_data = _load_strict_json(
            text[len(fence_open) : closing],
            f"{label} front-matter",
        )
        _require(
            isinstance(header_data, dict) and header_data.get("id") == entry_id,
            f"memory entry front-matter id mismatch: {entry_file.name}",
        )
        observed_ids.add(entry_id)

    _require(
        observed_ids == expected_ids,
        "memory entries directory files do not match index.json entry IDs",
    )


def _load_prereleases(root: Path) -> set[str]:
    raw = _load_strict_yaml(
        _read_regular_text(root, "pack/prereleases.yaml"),
        "pack/prereleases.yaml",
    )
    _require(
        isinstance(raw, dict) and set(raw) == {"packages"},
        "pack/prereleases.yaml must contain only 'packages'",
    )
    packages = raw["packages"]
    _require(
        isinstance(packages, list),
        "pack/prereleases.yaml packages must be a list",
    )
    seen: set[str] = set()
    for pkg in packages:
        _require(
            isinstance(pkg, str) and pkg in CANONICAL_PACKAGES,
            f"unknown prerelease package key: {pkg!r}",
        )
        _require(pkg not in seen, f"duplicate prerelease package key: {pkg!r}")
        seen.add(pkg)
    return seen


def _validate_packages(
    raw_packages: object,
    sub_id: str,
    prerelease_packages: set[str],
) -> None:
    if isinstance(raw_packages, list):
        items: list[tuple[str, dict[str, object]]] = []
        for idx, item in enumerate(raw_packages):
            _require(
                isinstance(item, dict),
                f"{sub_id} packages[{idx}] must be an object",
            )
            name = item.get("name")
            _require(
                isinstance(name, str) and name in CANONICAL_PACKAGES,
                f"{sub_id} unknown package name: {name!r}",
            )
            items.append((name, item))
    elif isinstance(raw_packages, dict):
        items = []
        for name, item in raw_packages.items():
            _require(
                isinstance(name, str) and name in CANONICAL_PACKAGES,
                f"{sub_id} unknown package name: {name!r}",
            )
            _require(
                isinstance(item, dict),
                f"{sub_id} packages[{name}] must be an object",
            )
            items.append((name, item))
    else:
        msg = f"{sub_id} packages must be a list or object"
        raise ValidationError(msg)

    seen: set[str] = set()
    for name, entry in items:
        _require(name not in seen, f"{sub_id} duplicate package entry: {name}")
        seen.add(name)
        decision = entry.get("decision")
        _require(
            decision in DECISIONS,
            f"{sub_id} package {name} has invalid decision: {decision!r}",
        )
        reason = entry.get("reason")
        _require(
            isinstance(reason, str) and bool(reason.strip()),
            f"{sub_id} package {name} requires a non-empty reason",
        )
        _validate_https_urls(entry.get("sources"), f"{sub_id} package {name} sources")
        ver = entry.get("version")
        if decision == "disable":
            _require(
                ver is None,
                f"{sub_id} disabled package {name} must have null version",
            )
        elif decision == "source":
            _require(
                isinstance(ver, str) and bool(re.fullmatch(r"[0-9a-f]{7,40}", ver)),
                f"{sub_id} source package {name} version must be 7-40 lowercase hex chars: {ver!r}",
            )
        else:
            parsed = _parse_bare_pep440(ver, f"{sub_id} package {name} version")
            if parsed.is_prerelease or parsed.is_devrelease:
                _require(
                    name in prerelease_packages,
                    f"{sub_id} package {name} prerelease {ver!r} is not whitelisted in pack/prereleases.yaml",
                )


def _validate_patches(root: Path, raw_patches: object, sub_id: str) -> None:
    _require(isinstance(raw_patches, list), f"{sub_id} patches must be a list")
    backend = sub_id.split("/", 1)[0]
    prefixes = BACKEND_WRITABLE_PATCH_PREFIXES[backend]
    seen_paths: set[str] = set()
    for idx, entry in enumerate(raw_patches):
        _require(isinstance(entry, dict), f"{sub_id} patches[{idx}] must be an object")
        path_str = entry.get("path")
        _require(
            isinstance(path_str, str)
            and path_str.endswith(".patch")
            and any(path_str.startswith(prefix) for prefix in prefixes),
            f"{sub_id} patch path must reside under writable patch dir for {backend}: {path_str!r}",
        )
        _require(
            path_str not in seen_paths,
            f"{sub_id} duplicate patch path: {path_str}",
        )
        seen_paths.add(path_str)
        disposition = entry.get("disposition")
        _require(
            disposition in DISPOSITIONS,
            f"{sub_id} patch {path_str} invalid disposition: {disposition!r}",
        )
        reason = entry.get("reason")
        _require(
            isinstance(reason, str) and bool(reason.strip()),
            f"{sub_id} patch {path_str} requires non-empty reason",
        )
        versions = entry.get("versions")
        _require(
            isinstance(versions, list) and bool(versions),
            f"{sub_id} patch {path_str} requires non-empty versions",
        )
        for ver in versions:
            _parse_bare_pep440(ver, f"{sub_id} patch {path_str} version")
        platforms = entry.get("platforms")
        _require(
            isinstance(platforms, list)
            and bool(platforms)
            and all(p in PLATFORMS for p in platforms),
            f"{sub_id} patch {path_str} has invalid platforms: {platforms!r}",
        )
        _validate_https_urls(entry.get("sources"), f"{sub_id} patch {path_str} sources")
        target = _safe_path(root, path_str)
        if disposition == "remove":
            _require(
                not target.exists(),
                f"{sub_id} removed patch still exists: {path_str}",
            )
        else:
            _require(target.is_file(), f"{sub_id} patch file is missing: {path_str}")
            _require(
                bool(target.read_text(encoding="utf-8").strip()),
                f"{sub_id} patch file is empty: {path_str}",
            )


def _validate_proposal(
    root: Path,
    prerelease_packages: set[str],
    *,
    proposal_path: str = PROPOSAL_REL_PATH,
) -> dict[str, dict[str, object]]:
    _require(
        proposal_path == PROPOSAL_REL_PATH,
        f".auto-sync/taskpack.yaml spec.proposal.path must be {PROPOSAL_REL_PATH!r}, got {proposal_path!r}",
    )
    legacy_autosync = root / ".autosync"
    _require(
        not legacy_autosync.exists() and not legacy_autosync.is_symlink(),
        "legacy .autosync path must not exist; use .auto-sync/proposal.json",
    )
    control_dir = _safe_path(root, CONTROL_ROOT)
    _require(control_dir.is_dir(), "missing required .auto-sync directory")
    for entry in sorted(control_dir.rglob("*")):
        _safe_path(root, entry.relative_to(root).as_posix())
    unexpected_control_entries = sorted(
        entry.name
        for entry in control_dir.iterdir()
        if entry.name not in {".DS_Store", "__pycache__"}
        and entry.name not in ALLOWED_CONTROL_ROOT_ENTRIES
    )
    _require(
        not unexpected_control_entries,
        f".auto-sync/ contains unexpected entries: {unexpected_control_entries}",
    )

    raw_taskpack = _load_strict_yaml(
        _read_regular_text(root, ".auto-sync/taskpack.yaml"),
        ".auto-sync/taskpack.yaml",
    )
    pin_digests = (
        isinstance(raw_taskpack, dict)
        and isinstance(raw_taskpack.get("spec"), dict)
        and isinstance(raw_taskpack["spec"].get("execution"), dict)
        and isinstance(raw_taskpack["spec"]["execution"].get("digests"), dict)
        and raw_taskpack["spec"]["execution"]["digests"].get("pinDigests") is True
    )
    digests_lock_file = root / DIGESTS_LOCK_REL_PATH
    if pin_digests or digests_lock_file.exists() or digests_lock_file.is_symlink():
        _require_non_hardlinked_regular_file(digests_lock_file, DIGESTS_LOCK_REL_PATH)
        lock_data = _load_strict_json(
            digests_lock_file.read_text(encoding="utf-8"),
            DIGESTS_LOCK_REL_PATH,
        )
        _require(
            isinstance(lock_data, dict)
            and type(lock_data.get("version")) is int
            and lock_data.get("version") == 1
            and lock_data.get("taskpack") == "auto-sync"
            and isinstance(lock_data.get("entries"), list)
            and bool(lock_data["entries"]),
            f"{DIGESTS_LOCK_REL_PATH} must be a valid version 1 auto-sync digest lockfile",
        )
        for lock_entry in lock_data["entries"]:
            _require(
                isinstance(lock_entry, dict)
                and isinstance(lock_entry.get("path"), str)
                and lock_entry.get("kind") in {"file", "directory"}
                and isinstance(lock_entry.get("sha256"), str)
                and bool(SHA256_HEX_RE.fullmatch(lock_entry["sha256"])),
                f"{DIGESTS_LOCK_REL_PATH} contains invalid entry: {lock_entry!r}",
            )

    proposal_file = _safe_path(root, PROPOSAL_REL_PATH)
    _require(
        proposal_file.is_file(),
        f"missing required regular file: {PROPOSAL_REL_PATH}",
    )
    _require(
        proposal_file.stat().st_nlink == 1,
        f"{PROPOSAL_REL_PATH} must not be hardlinked",
    )

    raw = _load_strict_json(
        _read_regular_text(root, PROPOSAL_REL_PATH),
        PROPOSAL_REL_PATH,
    )
    _require(isinstance(raw, dict), ".auto-sync/proposal.json must be a JSON object")
    allowed_top_keys = {
        "schema_version",
        "summary",
        "versions",
        "pack_run_url",
        "subscriptions",
    }
    unknown_top_keys = sorted(set(raw) - allowed_top_keys)
    _require(
        not unknown_top_keys,
        f".auto-sync/proposal.json contains unknown top-level keys: {unknown_top_keys}",
    )
    schema_version = raw.get("schema_version")
    _require(
        type(schema_version) is int and schema_version == 1,
        ".auto-sync/proposal.json schema_version must be integer 1",
    )
    summary = raw.get("summary")
    _require(
        isinstance(summary, str) and bool(summary.strip()),
        ".auto-sync/proposal.json summary must be a non-empty string",
    )

    parsed_versions: dict[str, Version] = {}
    if "versions" in raw:
        raw_versions = raw["versions"]
        _require(
            isinstance(raw_versions, dict),
            ".auto-sync/proposal.json versions must be a JSON object",
        )
        for upstream_id, ver_val in raw_versions.items():
            _require(
                isinstance(upstream_id, str) and upstream_id in UPSTREAM_IDS,
                f".auto-sync/proposal.json versions has unknown upstream key: {upstream_id!r}",
            )
            _require(
                isinstance(ver_val, str) and bool(ver_val.strip()),
                f".auto-sync/proposal.json versions[{upstream_id!r}] must be a non-empty version string",
            )
            _require(
                ver_val.strip() == ver_val,
                f".auto-sync/proposal.json versions[{upstream_id!r}] must not have surrounding whitespace",
            )
            try:
                parsed_ver = Version(ver_val)
            except InvalidVersion as exc:
                msg = (
                    f".auto-sync/proposal.json versions[{upstream_id!r}] "
                    f"invalid PEP 440 version {ver_val!r}: {exc}"
                )
                raise ValidationError(msg) from exc
            if upstream_id in {"vllm", "sglang"}:
                _require(
                    not parsed_ver.is_prerelease and not parsed_ver.is_devrelease,
                    f".auto-sync/proposal.json versions[{upstream_id!r}] must be stable: {ver_val!r}",
                )
            parsed_versions[upstream_id] = parsed_ver

    if "pack_run_url" in raw and raw["pack_run_url"] is not None:
        _validate_https_urls(
            [raw["pack_run_url"]],
            ".auto-sync/proposal.json pack_run_url",
        )

    raw_subs = raw.get("subscriptions")
    subs: dict[str, dict[str, object]] = {}
    if isinstance(raw_subs, dict):
        for key, value in raw_subs.items():
            _require(
                isinstance(key, str) and key in SUBSCRIPTIONS,
                f"unknown subscription in proposal: {key!r}",
            )
            _require(isinstance(value, dict), f"subscription {key} must be an object")
            subs[key] = value
    elif isinstance(raw_subs, list):
        for idx, item in enumerate(raw_subs):
            _require(isinstance(item, dict), f"subscriptions[{idx}] must be an object")
            key = item.get("subscription")
            _require(
                isinstance(key, str) and key in SUBSCRIPTIONS,
                f"unknown subscription in proposal: {key!r}",
            )
            _require(key not in subs, f"duplicate subscription in proposal: {key}")
            subs[key] = item
    else:
        msg = ".auto-sync/proposal.json subscriptions must be an object or list"
        raise ValidationError(msg)

    _require(
        set(subs) == set(SUBSCRIPTIONS),
        f"subscriptions must contain exactly {sorted(SUBSCRIPTIONS)}",
    )

    for sub_id, entry in subs.items():
        status = entry.get("status")
        _require(status in STATUSES, f"{sub_id} invalid status: {status!r}")
        reason = entry.get("reason")
        _require(
            isinstance(reason, str) and bool(reason.strip()),
            f"{sub_id} requires non-empty reason",
        )
        engine = entry.get("engine_version")
        plugin = entry.get("plugin_version")
        if status == "ready":
            parsed_engine = _parse_bare_pep440(engine, f"{sub_id} engine_version")
            _require(
                not parsed_engine.is_prerelease and not parsed_engine.is_devrelease,
                f"{sub_id} ready engine_version must be stable: {engine!r}",
            )
            if sub_id == "cann/vllm":
                _parse_bare_pep440(plugin, f"{sub_id} plugin_version")
            else:
                _require(plugin is None, f"{sub_id} plugin_version must be null")
            _validate_https_urls(
                entry.get("sources"),
                f"{sub_id} sources",
                allow_empty=False,
            )
        else:
            if engine is not None:
                _parse_bare_pep440(engine, f"{sub_id} engine_version")
            if sub_id == "cann/vllm":
                if plugin is not None:
                    _parse_bare_pep440(plugin, f"{sub_id} plugin_version")
            else:
                _require(plugin is None, f"{sub_id} plugin_version must be null")
            _validate_https_urls(entry.get("sources"), f"{sub_id} sources")

        _validate_packages(entry.get("packages"), sub_id, prerelease_packages)
        _validate_patches(root, entry.get("patches"), sub_id)

        if status in {"ready", "unchanged"}:
            upstream_key = (
                "vllm-ascend" if sub_id == "cann/vllm" else sub_id.split("/", 1)[1]
            )
            target_ver = plugin if sub_id == "cann/vllm" else engine
            if upstream_key in parsed_versions and target_ver is not None:
                expected_ver = Version(str(target_ver))
                _require(
                    parsed_versions[upstream_key] == expected_ver,
                    f".auto-sync/proposal.json versions[{upstream_key!r}] ({parsed_versions[upstream_key]}) does not match {sub_id} {status} version ({expected_ver})",
                )

    pack_run_url = os.environ.get("PACK_RUN_URL", "").strip()
    if pack_run_url:
        _require(
            bool(PACK_RUN_URL_RE.fullmatch(pack_run_url)),
            f"invalid PACK_RUN_URL: {pack_run_url!r}",
        )
        referenced = (
            raw.get("pack_run_url") == pack_run_url
            or pack_run_url in summary
            or any(
                pack_run_url in (entry.get("sources") or [])
                or pack_run_url in str(entry.get("reason", ""))
                for entry in subs.values()
            )
        )
        _require(
            referenced,
            f".auto-sync/proposal.json must reference PACK_RUN_URL ({pack_run_url})",
        )

    return subs


def _validate_matrix(root: Path) -> list[dict[str, object]]:
    raw = _load_strict_yaml(
        _read_regular_text(root, "pack/matrix.yaml"),
        "pack/matrix.yaml",
    )
    _require(
        isinstance(raw, dict) and set(raw) == {"rules"},
        "pack/matrix.yaml must contain only top-level 'rules'",
    )
    rules = raw["rules"]
    _require(
        isinstance(rules, list) and bool(rules),
        "pack/matrix.yaml rules must be a non-empty list",
    )
    for idx, rule in enumerate(rules):
        _require(
            isinstance(rule, dict)
            and {"backend", "services"}
            <= rule.keys()
            <= {"backend", "services", "platforms", "args"},
            f"pack/matrix.yaml rule[{idx}] has invalid keys",
        )
        _require(
            rule["backend"] in BACKENDS,
            f"pack/matrix.yaml rule[{idx}] unknown backend: {rule['backend']!r}",
        )
        services = rule["services"]
        _require(
            isinstance(services, list)
            and bool(services)
            and all(isinstance(s, str) and s in SERVICES for s in services)
            and len(set(services)) == len(services),
            f"pack/matrix.yaml rule[{idx}] invalid services",
        )
        if "platforms" in rule:
            platforms = rule["platforms"]
            _require(
                isinstance(platforms, list)
                and bool(platforms)
                and len(set(platforms)) == len(platforms)
                and all(
                    isinstance(p, str)
                    and bool(re.fullmatch(r"linux/(amd64|arm64)(/v[0-9]+)?", p))
                    for p in platforms
                ),
                f"pack/matrix.yaml rule[{idx}] invalid platforms",
            )
        if "args" in rule:
            args = rule["args"]
            _require(
                isinstance(args, list),
                f"pack/matrix.yaml rule[{idx}] args must be a list",
            )
            arg_names: set[str] = set()
            for arg in args:
                _require(
                    isinstance(arg, str)
                    and bool(
                        re.fullmatch(r"[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:+@,=-]*", arg),
                    ),
                    f"pack/matrix.yaml rule[{idx}] invalid arg: {arg!r}",
                )
                key = arg.split("=", 1)[0]
                _require(
                    key not in arg_names,
                    f"pack/matrix.yaml rule[{idx}] duplicate arg key: {key}",
                )
                arg_names.add(key)
    return rules


def _parse_dockerfile_args(text: str) -> dict[str, str]:
    args: dict[str, str] = {}
    for line in text.splitlines():
        if line.upper().startswith("FROM "):
            break
        match = re.fullmatch(r"ARG\s+([A-Z][A-Z0-9_]*)(?:=(.*))?", line.strip())
        if match:
            args[match[1]] = "" if match[2] is None else match[2].strip('"')
    return args


def _collect_patch_refs(text: str) -> tuple[set[str], set[tuple[str, str]]]:
    globs: set[str] = set()
    explicit: set[tuple[str, str]] = set()
    for subdir, filename in re.findall(
        r"(?:/workspace/)?patches/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.*-]+\.patch)",
        text,
    ):
        if filename == "*.patch":
            globs.add(subdir)
        else:
            explicit.add((subdir, filename))
    return globs, explicit


def _extract_cann_base_plugin_version(image: str, label: str) -> Version:
    _require(
        ":" in image,
        f"{label} CANN_BASE_IMAGE must include an explicit tag: {image!r}",
    )
    tag = image.rsplit(":", 1)[1].strip()
    stripped = tag.removeprefix("v")
    stripped = re.sub(
        r"(?:-(?:950|a5|a3|910b|910c|310p|openeuler))+$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return _parse_bare_pep440(stripped, f"{label} CANN_BASE_IMAGE tag")


def _validate_companion_arg(
    arg_key: str,
    val: str,
    label: str,
    prerelease_packages: set[str],
) -> None:
    pkg_key = COMPANION_ARG_TO_PACKAGE.get(arg_key)
    if pkg_key is None:
        return
    clean = val.strip()
    if not clean or COMMIT_SHA_RE.fullmatch(clean):
        return
    parsed = _parse_bare_pep440(clean, f"{label} {arg_key}")
    if parsed.is_prerelease or parsed.is_devrelease:
        _require(
            pkg_key in prerelease_packages,
            f"{label} {arg_key} prerelease {clean!r} is not whitelisted in pack/prereleases.yaml",
        )


def _validate_dockerfiles_and_patches(
    root: Path,
    rules: list[dict[str, object]],
    subs: dict[str, dict[str, object]],
    prerelease_packages: set[str],
    writable: tuple[str, ...],
    protected: tuple[str, ...],
    *,
    proposal_path: str | None = None,
) -> None:
    lmcache_pins: set[str] = set()
    dockerfile_globs: dict[tuple[str, str], set[str]] = {}
    dockerfile_explicit: dict[tuple[str, str], set[tuple[str, str]]] = {}

    for sub_id in SUBSCRIPTIONS:
        backend, service = sub_id.split("/", 1)
        rel = f"pack/{backend}/Dockerfile.{service}"
        text = _read_regular_text(root, rel)
        args = _parse_dockerfile_args(text)
        for req_arg in REQUIRED_DOCKERFILE_ARGS[(backend, service)]:
            _require(
                bool(args.get(req_arg, "").strip()),
                f"{rel} missing required non-empty ARG {req_arg}",
            )

        eng_arg_key = "VLLM_VERSION" if service == "vllm" else "SGLANG_VERSION"
        df_eng_ver = _parse_bare_pep440(args[eng_arg_key], f"{rel} {eng_arg_key}")
        _require(
            not df_eng_ver.is_prerelease and not df_eng_ver.is_devrelease,
            f"{rel} {eng_arg_key} must be stable: {args[eng_arg_key]!r}",
        )

        df_ascend_ver: Version | None = None
        df_base_plug_ver: Version | None = None
        if sub_id == "cann/vllm":
            if args.get("VLLM_ASCEND_VERSION", "").strip():
                df_ascend_ver = _parse_bare_pep440(
                    args["VLLM_ASCEND_VERSION"],
                    f"{rel} VLLM_ASCEND_VERSION",
                )
            df_base_plug_ver = _extract_cann_base_plugin_version(
                args["CANN_BASE_IMAGE"],
                rel,
            )

        for arg_key, arg_val in args.items():
            _validate_companion_arg(arg_key, arg_val, rel, prerelease_packages)

        if subs[sub_id]["status"] == "ready":
            expected_eng = Version(str(subs[sub_id]["engine_version"]))
            _require(
                df_eng_ver == expected_eng,
                f"{rel} {eng_arg_key} ({df_eng_ver}) does not match ready {sub_id} engine_version ({expected_eng})",
            )
            if sub_id == "cann/vllm":
                expected_plug = Version(str(subs[sub_id]["plugin_version"]))
                _require(
                    df_base_plug_ver == expected_plug,
                    f"{rel} CANN_BASE_IMAGE tag ({df_base_plug_ver}) does not match ready cann/vllm plugin_version ({expected_plug})",
                )
                if df_ascend_ver is not None:
                    _require(
                        df_ascend_ver == expected_plug,
                        f"{rel} VLLM_ASCEND_VERSION ({df_ascend_ver}) does not match ready cann/vllm plugin_version ({expected_plug})",
                    )

        if backend in {"cuda", "rocm"}:
            pin = args.get(f"{service.upper()}_LMCACHE_VERSION", "").strip()
            if pin:
                lmcache_pins.add(pin)
        globs, explicit = _collect_patch_refs(text)
        for subdir, filename in explicit:
            patch_rel = f"pack/{backend}/patches/{subdir}/{filename}"
            patch_path = _safe_path(root, patch_rel)
            _require(
                patch_path.is_file(),
                f"{rel} references missing patch: {patch_rel}",
            )
            _require(
                bool(patch_path.read_text(encoding="utf-8").strip()),
                f"{rel} references empty patch: {patch_rel}",
            )
        dockerfile_globs[(backend, service)] = globs
        dockerfile_explicit[(backend, service)] = explicit

    for rule in rules:
        backend = str(rule["backend"])
        rule_args = {
            arg.split("=", 1)[0]: arg.split("=", 1)[1]
            for arg in rule.get("args", [])
            if isinstance(arg, str) and "=" in arg
        }
        for service in rule["services"]:
            sub_id = f"{backend}/{service}"
            if sub_id not in SUBSCRIPTIONS:
                continue
            eng_arg_key = "VLLM_VERSION" if service == "vllm" else "SGLANG_VERSION"
            if rule_args.get(eng_arg_key, "").strip():
                rule_eng_ver = _parse_bare_pep440(
                    rule_args[eng_arg_key].strip(),
                    f"pack/matrix.yaml {sub_id} {eng_arg_key}",
                )
                _require(
                    not rule_eng_ver.is_prerelease and not rule_eng_ver.is_devrelease,
                    f"pack/matrix.yaml {sub_id} {eng_arg_key} must be stable: {rule_args[eng_arg_key]!r}",
                )
                if subs[sub_id]["status"] == "ready":
                    expected_eng = Version(str(subs[sub_id]["engine_version"]))
                    _require(
                        rule_eng_ver == expected_eng,
                        f"pack/matrix.yaml {sub_id} {eng_arg_key} ({rule_eng_ver}) does not match ready engine_version ({expected_eng})",
                    )

            if sub_id == "cann/vllm":
                if rule_args.get("VLLM_ASCEND_VERSION", "").strip():
                    rule_ascend_ver = _parse_bare_pep440(
                        rule_args["VLLM_ASCEND_VERSION"].strip(),
                        "pack/matrix.yaml cann/vllm VLLM_ASCEND_VERSION",
                    )
                    if subs[sub_id]["status"] == "ready":
                        expected_plug = Version(str(subs[sub_id]["plugin_version"]))
                        _require(
                            rule_ascend_ver == expected_plug,
                            f"pack/matrix.yaml cann/vllm VLLM_ASCEND_VERSION ({rule_ascend_ver}) does not match ready plugin_version ({expected_plug})",
                        )
                if rule_args.get("CANN_BASE_IMAGE", "").strip():
                    rule_base_plug_ver = _extract_cann_base_plugin_version(
                        rule_args["CANN_BASE_IMAGE"].strip(),
                        "pack/matrix.yaml cann/vllm",
                    )
                    if subs[sub_id]["status"] == "ready":
                        expected_plug = Version(str(subs[sub_id]["plugin_version"]))
                        _require(
                            rule_base_plug_ver == expected_plug,
                            f"pack/matrix.yaml cann/vllm CANN_BASE_IMAGE tag ({rule_base_plug_ver}) does not match ready plugin_version ({expected_plug})",
                        )

            for arg_key, arg_val in rule_args.items():
                _validate_companion_arg(
                    arg_key,
                    arg_val,
                    f"pack/matrix.yaml {sub_id}",
                    prerelease_packages,
                )

            if backend in {"cuda", "rocm"}:
                lmcache_key = f"{service.upper()}_LMCACHE_VERSION"
                val = rule_args.get(lmcache_key, "").strip()
                if val:
                    lmcache_pins.add(val)

    _require(
        len(lmcache_pins) <= 1,
        f"LMCache pins across cuda/rocm vllm/sglang must match, found {sorted(lmcache_pins)}",
    )

    for backend in SYNCED_PACK_BACKENDS:
        backend_root_rel = f"pack/{backend}"
        backend_root = _safe_path(root, backend_root_rel)
        _require(
            backend_root.is_dir(),
            f"missing synced backend directory: {backend_root_rel}",
        )
        allowed_dockerfiles = {
            f"pack/{backend}/Dockerfile.vllm",
            f"pack/{backend}/Dockerfile.sglang",
        }
        for entry in sorted(backend_root.rglob("*")):
            rel = entry.relative_to(root).as_posix()
            _safe_path(root, rel)
            if entry.name == ".DS_Store" or "__pycache__" in entry.parts:
                continue
            if (
                classify_scope_path(
                    rel,
                    writable,
                    protected,
                    proposal_path=proposal_path,
                )
                == "protected"
            ):
                continue
            if entry.is_dir():
                continue
            _require(entry.is_file(), f"pack entry must be a regular file: {rel}")
            if rel in allowed_dockerfiles:
                continue
            parts = PurePosixPath(rel).parts
            _require(
                len(parts) == 5 and parts[2] == "patches" and entry.suffix == ".patch",
                f"unexpected non-protected file in writable pack directory: {rel}",
            )
            _require(
                bool(entry.read_text(encoding="utf-8").strip()),
                f"patch file must not be empty: {rel}",
            )
            subdir, filename = parts[3], parts[4]
            owner_service = (
                "sglang"
                if subdir == "sglang"
                else (
                    "vllm"
                    if subdir in {"vllm", "vllm_omni"}
                    or (backend == "cann" and subdir == "vllm_ascend")
                    else None
                )
            )
            _require(
                owner_service is not None,
                f"unreferenced patch subdirectory: {rel}",
            )
            globs = dockerfile_globs[(backend, owner_service)]
            explicit = dockerfile_explicit[(backend, owner_service)]
            _require(
                subdir in globs or (subdir, filename) in explicit,
                f"unreferenced patch file (not hooked in pack/{backend}/Dockerfile.{owner_service}): {rel}",
            )


def _canonical_variant(backend: str, variant: str) -> str:
    value = variant.strip().lower()
    if backend == "cann" and value in CANN_ALIASES:
        return CANN_ALIASES[value]
    if backend != "cann" and value in {"", "-"}:
        return ""
    msg = f"unknown {backend} variant in support records: {variant!r}"
    raise ValidationError(msg)


def _parse_table_cells(line: str) -> list[str]:
    _require(
        line.startswith("|") and line.endswith("|"),
        f"malformed support table row: {line}",
    )
    return [cell.strip() for cell in line[1:-1].split("|")]


def _parse_support_records(text: str) -> list[dict[str, object]]:
    _require(
        text.count(SUPPORT_START) == 1
        and text.count(SUPPORT_END) == 1
        and text.index(SUPPORT_START) < text.index(SUPPORT_END),
        "docs/support-records.md missing or duplicate support record markers",
    )
    body = text.split(SUPPORT_START)[1].split(SUPPORT_END)[0]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    _require(len(lines) >= 2, "docs/support-records.md missing table header")
    header = _parse_table_cells(lines[0])
    separator = _parse_table_cells(lines[1])
    _require(header == SUPPORT_COLUMNS, "docs/support-records.md unexpected columns")
    _require(
        len(separator) == len(header)
        and all(re.fullmatch(r":?-{3,}:?", col) for col in separator),
        "docs/support-records.md malformed table separator",
    )

    records: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for line in lines[2:]:
        cells = _parse_table_cells(line)
        _require(
            len(cells) == len(header),
            "docs/support-records.md row column count mismatch",
        )
        backend, runtime, service, variant, engine, plugin, platforms_raw, status = (
            cells
        )
        _require(
            backend in BACKENDS,
            f"docs/support-records.md unknown backend: {backend!r}",
        )
        _require(
            service in SERVICES,
            f"docs/support-records.md unknown service: {service!r}",
        )
        _require(
            bool(re.fullmatch(r"[0-9]+\.[0-9]+", runtime)),
            f"docs/support-records.md runtime must be major.minor line: {runtime!r}",
        )
        _require(
            status in {"prepared", "published"},
            f"docs/support-records.md invalid status: {status!r}",
        )
        norm_variant = _canonical_variant(backend, variant)
        norm_plugin = None if plugin == "-" else plugin
        _require(
            (backend == "cann" and service == "vllm") == (norm_plugin is not None),
            "docs/support-records.md CANN vLLM requires an actual plugin version; other rows use '-'",
        )
        eng_ver = _parse_bare_pep440(engine, "docs/support-records.md Engine")
        plug_ver = (
            _parse_bare_pep440(norm_plugin, "docs/support-records.md Plugin")
            if norm_plugin is not None
            else None
        )
        platforms = [p.strip() for p in platforms_raw.split(",")]
        _require(
            bool(platforms)
            and len(set(platforms)) == len(platforms)
            and all(
                re.fullmatch(r"linux/(amd64|arm64)(/v[0-9]+)?", p) for p in platforms
            ),
            f"docs/support-records.md invalid platforms: {platforms_raw!r}",
        )
        identity = (
            backend,
            service,
            norm_variant,
            eng_ver,
            plug_ver,
            Version(runtime),
            tuple(sorted(platforms)),
        )
        _require(
            identity not in seen,
            "docs/support-records.md duplicate support identity",
        )
        seen.add(identity)
        records.append(
            {
                "backend": backend,
                "runtime": runtime,
                "service": service,
                "variant": norm_variant,
                "engine": str(eng_ver),
                "plugin": str(plug_ver) if plug_ver is not None else None,
                "platforms": platforms,
                "status": status,
            },
        )
    return records


def _runtime_version(backend: str, runtime: str) -> Version:
    parsed = Version(runtime)
    if backend == "cann":
        return Version(f"{parsed.major}.{parsed.minor}")
    return parsed


def _load_promote_support_module(root: Path):
    promote_path = _safe_path(root, "pack/promote_support.py")
    _require(
        promote_path.is_file(),
        "missing required regular file: pack/promote_support.py",
    )
    spec = importlib.util.spec_from_file_location(
        "candidate_promote_support",
        promote_path,
    )
    if spec is None or spec.loader is None:
        msg = "unable to load pack/promote_support.py"
        raise ValidationError(msg)
    module = importlib.util.module_from_spec(spec)
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prev_dont_write
    return module


def _validate_pack_scripts(root: Path, rules: list[dict[str, object]]) -> None:
    resolve_script = _safe_path(root, "pack/resolve_dockerfile.sh")
    _require(
        resolve_script.is_file(),
        "missing required regular file: pack/resolve_dockerfile.sh",
    )
    expand_script = _safe_path(root, "pack/expand_matrix.sh")
    _require(
        expand_script.is_file(),
        "missing required regular file: pack/expand_matrix.sh",
    )
    bash_bin = shutil.which("bash") or "/bin/bash"

    pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for rule in rules:
        backend = str(rule["backend"])
        services = rule["services"]
        if not isinstance(services, list):
            continue
        for service in services:
            pair = (backend, str(service))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                pairs.append(pair)

    for backend, service in pairs:
        res = subprocess.run(  # noqa: S603 - fixed repository resolver script.
            [bash_bin, str(resolve_script), str(root / "pack"), backend, service],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        _require(
            res.returncode == 0,
            f"pack/resolve_dockerfile.sh failed for {backend}/{service}: {res.stderr.strip() or res.stdout.strip()}",
        )
        resolved_out = res.stdout.strip()
        _require(
            bool(resolved_out),
            f"pack/resolve_dockerfile.sh returned empty output for {backend}/{service}",
        )
        resolved_path = Path(resolved_out)
        if not resolved_path.is_absolute():
            resolved_path = root / resolved_path
        resolved_abs = resolved_path.resolve()
        _require(
            resolved_abs.is_relative_to(root) and resolved_abs.is_file(),
            f"pack/resolve_dockerfile.sh resolved missing file for {backend}/{service}: {resolved_out}",
        )

    if shutil.which("yq") and shutil.which("jq"):
        with tempfile.TemporaryDirectory() as tmp_dir:
            gh_output = Path(tmp_dir) / "github_output.txt"
            expand_res = subprocess.run(  # noqa: S603 - fixed repository matrix expander.
                [bash_bin, str(expand_script)],
                cwd=root,
                env={
                    **os.environ,
                    "INPUT_WORKSPACE": str(root / "pack"),
                    "INPUT_TARGET": "vllm",
                    "INPUT_BACKEND": "all",
                    "INPUT_FOR_RELEASE": "true",
                    "INPUT_RUNNER_PROFILE": "normal",
                    "INPUT_TEMPDIR": tmp_dir,
                    "GITHUB_OUTPUT": str(gh_output),
                },
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            _require(
                expand_res.returncode == 0,
                f"pack/expand_matrix.sh failed: {expand_res.stderr.strip() or expand_res.stdout.strip()}",
            )
            _require(
                gh_output.is_file(),
                "pack/expand_matrix.sh did not write GITHUB_OUTPUT",
            )
            build_jobs: object = None
            for line in gh_output.read_text(encoding="utf-8").splitlines():
                if line.startswith("build_jobs="):
                    build_jobs = _load_strict_json(
                        line.split("=", 1)[1],
                        "pack/expand_matrix.sh build_jobs",
                    )
                    break
            _require(
                isinstance(build_jobs, list) and bool(build_jobs),
                "pack/expand_matrix.sh must produce a non-empty build_jobs JSON list",
            )


def _validate_support_records(root: Path, subs: dict[str, dict[str, object]]) -> None:
    readme_text = _read_regular_text(root, "README.md")
    _require(
        "docs/supported-runners.md" in readme_text,
        "README.md must contain link to docs/supported-runners.md",
    )
    supported_runners_text = _read_regular_text(root, "docs/supported-runners.md")
    _require(
        bool(supported_runners_text.strip()),
        "docs/supported-runners.md must not be empty",
    )

    promote_mod = _load_promote_support_module(root)
    try:
        parsed_supported = promote_mod.parse_support(supported_runners_text)
    except promote_mod.PromoteSupportError as exc:
        msg = f"docs/supported-runners.md invalid support table: {exc}"
        raise ValidationError(msg) from exc
    historical_records = [
        item for item in parsed_supported if item.get("status") == "historical"
    ]
    historical_identities = {
        (
            str(item["backend"]),
            str(item["service"]),
            Version(str(item["engine_version"])),
        )
        for item in historical_records
    }
    historical_group_keys = {
        (
            str(item["backend"]),
            _runtime_version(str(item["backend"]), str(item["runtime"])),
            str(item["service"]),
            str(item["variant"]),
            Version(str(item["engine_version"])),
        )
        for item in historical_records
    }

    records = _parse_support_records(
        _read_regular_text(root, "docs/support-records.md"),
    )
    catalog_raw = _load_strict_json(
        _read_regular_text(root, "gpustack_runner/runner.py.json"),
        "gpustack_runner/runner.py.json",
    )
    _require(
        isinstance(catalog_raw, list),
        "gpustack_runner/runner.py.json must be a JSON array",
    )

    measured_with_plugin: set[tuple[str, str, str, str, Version, Version | None]] = (
        set()
    )
    active_subscribed_catalog: set[tuple[str, str, Version]] = set()
    catalog_group_platforms: dict[tuple[str, Version, str, str, Version], set[str]] = {}
    active_group_platforms: dict[tuple[str, Version, str, str, Version], set[str]] = {}
    for entry in catalog_raw:
        if not isinstance(entry, dict):
            continue
        backend = entry.get("backend")
        runtime = entry.get("backend_version")
        service = entry.get("service")
        variant = entry.get("backend_variant") or ""
        service_version = entry.get("service_version")
        platform = entry.get("platform")
        if not all(
            isinstance(v, str) and v
            for v in (backend, runtime, service, service_version)
        ):
            continue
        try:
            eng_ver = Version(service_version)
            rt_ver = _runtime_version(backend, runtime)
            norm_variant = promote_mod.canonical_variant(
                backend,
                variant if isinstance(variant, str) else "",
            )
        except (InvalidVersion, promote_mod.PromoteSupportError):
            continue
        group_key = (backend, rt_ver, service, norm_variant, eng_ver)
        if isinstance(platform, str) and platform:
            catalog_group_platforms.setdefault(group_key, set()).add(platform)
        if (
            not entry.get("deprecated", False)
            and backend in {"cuda", "rocm", "cann"}
            and service in {"vllm", "sglang"}
        ):
            active_subscribed_catalog.add((backend, service, eng_ver))
            if isinstance(platform, str) and platform:
                active_group_platforms.setdefault(group_key, set()).add(platform)
        deps = entry.get("dependencies")
        plugin_raw = deps.get("vllm-ascend") if isinstance(deps, dict) else None
        plug_ver: Version | None = None
        if isinstance(plugin_raw, str) and plugin_raw:
            try:
                plug_ver = Version(plugin_raw)
            except InvalidVersion:
                plug_ver = None
        measured_with_plugin.add(
            (backend, runtime, service, variant.lower(), eng_ver, plug_ver),
        )

    ready_new: set[tuple[str, str, Version, Version | None]] = set()
    for sub_id, entry in subs.items():
        if entry["status"] != "ready":
            continue
        backend, service = sub_id.split("/", 1)
        eng_ver = Version(str(entry["engine_version"]))
        plug_ver = (
            Version(str(entry["plugin_version"]))
            if entry.get("plugin_version") is not None
            else None
        )
        has_prepared = any(
            record["status"] == "prepared"
            and record["backend"] == backend
            and record["service"] == service
            and Version(str(record["engine"])) == eng_ver
            and (
                sub_id != "cann/vllm"
                or (
                    record["plugin"] is not None
                    and Version(str(record["plugin"])) == plug_ver
                )
            )
            for record in records
        )
        _require(
            has_prepared,
            f"ready subscription {sub_id} {eng_ver} requires at least one 'prepared' row in docs/support-records.md",
        )
        is_published = any(
            m[0] == backend
            and m[2] == service
            and m[4] == eng_ver
            and (backend != "cann" or service != "vllm" or m[5] == plug_ver)
            for m in measured_with_plugin
        )
        if not is_published:
            ready_new.add((backend, service, eng_ver, plug_ver))

    published_identities: set[tuple[str, str, Version]] = set()
    cand_published_rows: set[tuple[object, ...]] = set()
    published_group_platforms: dict[
        tuple[str, Version, str, str, Version],
        set[tuple[str, ...]],
    ] = {}
    for record in records:
        rec_group_key = (
            str(record["backend"]),
            _runtime_version(
                str(record["backend"]),
                str(record["runtime"]),
            ),
            str(record["service"]),
            str(record["variant"]),
            Version(str(record["engine"])),
        )
        rec_plug = (
            Version(str(record["plugin"])) if record["plugin"] is not None else None
        )
        if record["status"] == "published":
            _require(
                rec_group_key in catalog_group_platforms,
                f"forged published support record not in gpustack_runner/runner.py.json: {record['backend']}/{record['runtime']}/{record['service']}/{record['variant'] or '-'}/{record['engine']}",
            )
            published_identities.add(
                (
                    str(record["backend"]),
                    str(record["service"]),
                    Version(str(record["engine"])),
                ),
            )
            platforms = record["platforms"]
            if not isinstance(platforms, list):
                continue
            rec_plats = tuple(sorted(str(p) for p in platforms))
            expected_plats = tuple(sorted(catalog_group_platforms[rec_group_key]))
            _require(
                rec_plats == expected_plats,
                f"published support record platforms mismatch in docs/support-records.md for {record['backend']}/{record['runtime']}/{record['service']}/{record['variant'] or '-'}/{record['engine']}: expected {expected_plats}, found {rec_plats}",
            )
            published_group_platforms.setdefault(rec_group_key, set()).add(rec_plats)
            cand_published_rows.add(
                (
                    str(record["backend"]),
                    Version(str(record["runtime"])),
                    str(record["service"]),
                    str(record["variant"]),
                    Version(str(record["engine"])),
                    rec_plug,
                    rec_plats,
                ),
            )
        if (
            record["backend"],
            record["service"],
            Version(str(record["engine"])),
            rec_plug,
        ) in ready_new:
            _require(
                record["status"] == "prepared",
                f"newly proposed release {record['backend']}/{record['service']} {record['engine']} must have status 'prepared'",
            )

    missing_measured = active_subscribed_catalog - (
        published_identities | historical_identities
    )
    if missing_measured:
        sample = sorted(missing_measured, key=str)[0]
        msg = f"measured subscribed runner missing from support docs: {sample}"
        raise ValidationError(msg)

    for group_key, plats in active_group_platforms.items():
        expected_plats = tuple(sorted(plats))
        if group_key not in historical_group_keys:
            _require(
                expected_plats in published_group_platforms.get(group_key, set()),
                f"non-historical measured subscribed runner missing published row in docs/support-records.md: {group_key[0]}/{group_key[1]}/{group_key[2]}/{group_key[3] or '-'}/{group_key[4]}",
            )

    for sub_id in SUBSCRIPTIONS:
        sub_backend, sub_service = sub_id.split("/", 1)
        max_eng = max(
            (
                key[4]
                for key in active_group_platforms
                if key[0] == sub_backend and key[2] == sub_service
            ),
            default=None,
        )
        if max_eng is None:
            continue
        for group_key, plats in active_group_platforms.items():
            if (
                group_key[0] == sub_backend
                and group_key[2] == sub_service
                and group_key[4] == max_eng
            ):
                expected_plats = tuple(sorted(plats))
                _require(
                    expected_plats in published_group_platforms.get(group_key, set()),
                    f"latest measured published support record missing from docs/support-records.md: {group_key[0]}/{group_key[1]}/{group_key[2]}/{group_key[3] or '-'}/{group_key[4]}",
                )

    baseline_support_text: str | None = None
    if (root / ".git").exists():
        git_bin = shutil.which("git")
        if git_bin is not None:
            head_res = subprocess.run(  # noqa: S603 - fixed read-only git show on candidate root.
                [git_bin, "-C", str(root), "show", "HEAD:docs/support-records.md"],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            if head_res.returncode == 0:
                baseline_support_text = head_res.stdout
    else:
        base_dir = _resolve_base_snapshot_dir()
        if base_dir is not None and (base_dir / "docs" / "support-records.md").exists():
            baseline_support_text = _read_regular_text(
                base_dir,
                "docs/support-records.md",
            )

    if baseline_support_text is not None:
        head_records = _parse_support_records(baseline_support_text)
        head_published_rows = {
            (
                str(r["backend"]),
                Version(str(r["runtime"])),
                str(r["service"]),
                str(r["variant"]),
                Version(str(r["engine"])),
                Version(str(r["plugin"])) if r["plugin"] is not None else None,
                tuple(sorted(str(p) for p in r["platforms"])),
            )
            for r in head_records
            if r["status"] == "published" and isinstance(r["platforms"], list)
        }
        deleted_published = head_published_rows - cand_published_rows
        if deleted_published:
            sample = sorted(deleted_published, key=str)[0]
            msg = f"docs/support-records.md deleted or altered existing published row: {sample}"
            raise ValidationError(msg)


def validate_candidate(candidate_dir: Path) -> None:
    root = candidate_dir.resolve()
    _require(root.is_dir(), f"candidate directory does not exist: {candidate_dir}")
    writable, effective_protected, _, proposal_path = _load_scope_and_proposal_path(
        root,
    )
    _validate_git_scope(
        root,
        writable,
        effective_protected,
        proposal_path=proposal_path,
    )
    _validate_memory_store(root)
    prerelease_packages = _load_prereleases(root)
    subs = _validate_proposal(root, prerelease_packages, proposal_path=proposal_path)
    rules = _validate_matrix(root)
    _validate_dockerfiles_and_patches(
        root,
        rules,
        subs,
        prerelease_packages,
        writable,
        effective_protected,
        proposal_path=proposal_path,
    )
    _validate_pack_scripts(root, rules)
    _validate_support_records(root, subs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        default=None,
        help="Path to candidate workspace directory.",
    )
    args = parser.parse_args(argv)
    candidate_dir = args.candidate_dir
    if candidate_dir is None:
        candidate_dir = Path(os.environ.get("LOOPWRIGHT_CANDIDATE_DIR") or Path.cwd())
    try:
        validate_candidate(candidate_dir)
    except (ValidationError, OSError, UnicodeDecodeError) as exc:
        print(f"candidate validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
