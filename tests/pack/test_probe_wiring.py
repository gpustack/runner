"""Structural invariant tests for the dependency-probe wiring in pack/.

pack.yml is `workflow_dispatch` only, so no pull request ever builds an image: a
missing or mis-wired probe produces no CI signal at all, and surfaces only when
someone dispatches a build or cuts a release. This file is that missing signal.

Coverage is derived, not hardcoded. The (backend, service) pairs come from
pack/matrix.yaml, and each pair is resolved to a Dockerfile the same way pack.yml
does -- `Dockerfile.<service>` wins over the merged `Dockerfile` when it exists.
So only the targets that are actually buildable are required to carry the probe,
and a merged Dockerfile left stale by the per-service split is not. Adding a
backend, a service, or a matrix rule extends this coverage on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "pack"

REPO_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pack.yml"
MATRIX_YAML = PACK_DIR / "matrix.yaml"

_YAML_LIST_ITEM_RE = re.compile(r"^\s*-\s*\"?([A-Za-z0-9][A-Za-z0-9_.-]*)\"?\s*$")
_YAML_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+):\s*$")
_RULE_BACKEND_RE = re.compile(r"^\s*-\s+backend:\s*\"?([A-Za-z0-9_-]+)\"?\s*$")

# The file-resolution rule this module mirrors, as it appears in pack.yml.
_WORKFLOW_DOCKERFILE_PREFERENCE = "if [[ -f ${DOCKER_FILE}.${{ matrix.service }} ]]"


def _yaml_list_items(lines: list[str], start: int) -> list[str]:
    """Collect the `- item` entries of the YAML block sequence starting at `start`."""
    items: list[str] = []
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _YAML_LIST_ITEM_RE.match(line)
        if not m:
            break
        items.append(m.group(1))
    return items


def _matrix_build_pairs() -> set[tuple[str, str]]:
    """Every (backend, service) pair pack/matrix.yaml expands into.

    matrix.yaml is where a service actually enters the build -- expand_matrix.sh
    derives `matrix.backend` and `matrix.service` from `rules[]` -- so a target
    absent from here is one no build can ever reach.
    """
    lines = MATRIX_YAML.read_text(encoding="utf-8").splitlines()
    pairs: set[tuple[str, str]] = set()
    backend: str | None = None
    for i, line in enumerate(lines):
        m = _RULE_BACKEND_RE.match(line)
        if m:
            backend = m.group(1)
            continue
        km = _YAML_KEY_RE.match(line)
        if backend and km and km.group(2) == "services":
            pairs.update((backend, s) for s in _yaml_list_items(lines, i + 1))
    if not pairs:
        errmsg = (
            f"no (backend, service) pairs found in {MATRIX_YAML} -- the matrix "
            f"layout changed, and every test in this file would otherwise "
            f"silently cover nothing"
        )
        raise RuntimeError(errmsg)
    return pairs


def _resolve_dockerfile(backend: str, service: str) -> Path:
    """Pick the Dockerfile a build would use, mirroring pack.yml's rule."""
    split = PACK_DIR / backend / f"Dockerfile.{service}"
    return split if split.is_file() else PACK_DIR / backend / "Dockerfile"


# The buildable (Dockerfile, service target) pairs -- the only ones that must
# carry the probe. A merged Dockerfile that every service has since outgrown a
# split file for resolves to nothing here and is left alone.
BUILD_TARGETS = sorted(
    (_resolve_dockerfile(backend, service), service)
    for backend, service in _matrix_build_pairs()
)

# `AS` is matched case-insensitively even though the repo currently always uppercases
# it -- don't assume that stays true forever.
FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
ARG_DEPS_RE = re.compile(r"^ARG\s+DEPENDENCY_PACKAGES(?:=.*)?\s*$")
COPY_FROM_RE = re.compile(r"^COPY\s+--from=(\S+)\s")
BUILD_STEP_RE = re.compile(r"^(RUN|COPY|ADD)\b", re.IGNORECASE)
# Matching the mounted script name too, not just the shared context: mounting
# pack/shared/ to run something else is not a probe call.
PROBE_RUN_PREFIX = "RUN --mount=type=bind,from=shared,source=probe_dependencies.sh"


@dataclass
class Stage:
    name: str
    base: str
    from_line: int  # 1-indexed line number of the `FROM` instruction itself
    body: list[tuple[int, str]]  # (line_no, text) for lines strictly after FROM,
    # up to (not including) the next FROM, or EOF for the last stage.


@dataclass
class ParsedDockerfile:
    path: Path
    preamble: list[tuple[int, str]]  # lines before the first FROM
    stages: list[Stage]

    def stage(self, name: str) -> Stage | None:
        for s in self.stages:
            if s.name == name:
                return s
        return None


def parse_dockerfile(path: Path) -> ParsedDockerfile:
    lines = path.read_text(encoding="utf-8").splitlines()
    froms: list[tuple[int, str, str | None]] = []
    for i, line in enumerate(lines, start=1):
        m = FROM_RE.match(line)
        if m:
            froms.append((i, m.group(1), m.group(2)))

    first_from_line = froms[0][0] if froms else len(lines) + 1
    preamble = [(i, lines[i - 1]) for i in range(1, first_from_line)]

    stages = []
    for idx, (from_line, base, name) in enumerate(froms):
        end = froms[idx + 1][0] if idx + 1 < len(froms) else len(lines) + 1
        body = [(j, lines[j - 1]) for j in range(from_line + 1, end)]
        if name is not None:
            stages.append(Stage(name=name, base=base, from_line=from_line, body=body))

    return ParsedDockerfile(path=path, preamble=preamble, stages=stages)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _probe_lines(body: list[tuple[int, str]]) -> list[int]:
    return [ln for ln, text in body if text.lstrip().startswith(PROBE_RUN_PREFIX)]


def _arg_lines(body: list[tuple[int, str]]) -> list[int]:
    return [ln for ln, text in body if ARG_DEPS_RE.match(text.strip())]


PACK_DOCKERFILES = sorted({path for path, _ in BUILD_TARGETS})
PARSED = {p: parse_dockerfile(p) for p in PACK_DOCKERFILES}

# The service targets each Dockerfile is actually built for. A file may define
# more stages than this -- only the buildable ones are held to the invariants.
TARGET_NAMES = {
    path: {service for p, service in BUILD_TARGETS if p == path}
    for path in PACK_DOCKERFILES
}


def _service_targets(parsed: ParsedDockerfile) -> list[Stage]:
    names = TARGET_NAMES[parsed.path]
    return [s for s in parsed.stages if s.name in names]


def _deps_stages(parsed: ParsedDockerfile) -> list[Stage]:
    """The `-deps` export stages belonging to this file's buildable targets."""
    wanted = {f"{name}-deps" for name in TARGET_NAMES[parsed.path]}
    return [s for s in parsed.stages if s.name in wanted]


def test_discovery_found_build_targets():
    # If this ever comes back empty, every other test here passes vacuously.
    assert BUILD_TARGETS, (
        f"no buildable (Dockerfile, service) pair resolved from {MATRIX_YAML}"
    )
    missing = sorted(_rel(p) for p in PACK_DOCKERFILES if not p.is_file())
    assert not missing, (
        f"matrix.yaml names backends whose Dockerfile does not exist: {missing}"
    )


def test_workflow_still_prefers_the_split_dockerfile():
    """The file-resolution rule `_resolve_dockerfile` mirrors still lives in pack.yml.

    Without this, a change to how the workflow picks a Dockerfile would silently
    shift which targets get built, while this module kept checking the old set.
    """
    # Via a local, so a failure does not dump the whole workflow file.
    found = _WORKFLOW_DOCKERFILE_PREFERENCE in REPO_WORKFLOW.read_text(
        encoding="utf-8",
    )
    assert found, (
        f"{_rel(REPO_WORKFLOW)} no longer contains "
        f"'{_WORKFLOW_DOCKERFILE_PREFERENCE}' -- the Dockerfile selection rule "
        f"changed, so `_resolve_dockerfile` in this module must change with it"
    )


@pytest.mark.parametrize("path", PACK_DOCKERFILES, ids=_rel)
def test_every_service_target_has_a_deps_export_stage(path: Path):
    """Invariant 1: every service target has a matching `<service>-deps` stage."""
    parsed = PARSED[path]
    for stage in _service_targets(parsed):
        deps_name = f"{stage.name}-deps"
        assert parsed.stage(deps_name) is not None, (
            f"{_rel(path)}:{stage.from_line}: service target '{stage.name}' has "
            f"no matching export stage '{deps_name}' -- the dependency probe "
            f"export is missing for this target"
        )


@pytest.mark.parametrize("path", PACK_DOCKERFILES, ids=_rel)
def test_deps_stage_is_scratch_and_names_a_real_target(path: Path):
    """Invariant 2: every `-deps` stage is `FROM scratch` and names a real target."""
    parsed = PARSED[path]
    service_names = {s.name for s in _service_targets(parsed)}
    for stage in _deps_stages(parsed):
        assert stage.base.lower() == "scratch", (
            f"{_rel(path)}:{stage.from_line}: export stage '{stage.name}' must "
            f"be 'FROM scratch', found 'FROM {stage.base}'"
        )
        target_name = stage.name[: -len("-deps")]
        assert target_name in service_names, (
            f"{_rel(path)}:{stage.from_line}: export stage '{stage.name}' does "
            f"not correspond to a real service target named '{target_name}' in "
            f"this file (service targets found: {sorted(service_names)})"
        )


@pytest.mark.parametrize("path", PACK_DOCKERFILES, ids=_rel)
def test_deps_stage_copies_from_its_own_target(path: Path):
    """Invariant 3: a `-deps` stage's `COPY --from=X` must be its own target.

    This guards against cross-target copy-paste in a multi-service file such as
    pack/musa/Dockerfile, which defines vllm and sglang side by side.
    """
    parsed = PARSED[path]
    for stage in _deps_stages(parsed):
        target_name = stage.name[: -len("-deps")]
        copy_from = None
        copy_line = None
        for ln, text in stage.body:
            m = COPY_FROM_RE.match(text.strip())
            if m:
                copy_from, copy_line = m.group(1), ln
                break
        assert copy_from is not None, (
            f"{_rel(path)}:{stage.from_line}: export stage '{stage.name}' has "
            f"no 'COPY --from=...' instruction"
        )
        assert copy_from == target_name, (
            f"{_rel(path)}:{copy_line}: export stage '{stage.name}' copies "
            f"from '{copy_from}', expected '{target_name}' -- looks like a "
            f"cross-target copy-paste mistake"
        )


@pytest.mark.parametrize("path", PACK_DOCKERFILES, ids=_rel)
def test_probe_call_count_and_arg_placement(path: Path):
    """Invariant 4: probe-call count == service-target count, each preceded by
    its own `ARG DEPENDENCY_PACKAGES`."""
    parsed = PARSED[path]
    targets = _service_targets(parsed)

    all_probe_lines = [ln for s in parsed.stages for ln in _probe_lines(s.body)]
    assert len(all_probe_lines) == len(targets), (
        f"{_rel(path)}: found {len(all_probe_lines)} probe_dependencies.sh "
        f"invocation(s) at line(s) {all_probe_lines}, but {len(targets)} "
        f"service target(s) ({sorted(s.name for s in targets)}) -- every "
        f"service target must call the probe exactly once, with no "
        f"extra/missing calls"
    )

    for stage in targets:
        probe_lines = _probe_lines(stage.body)
        assert len(probe_lines) == 1, (
            f"{_rel(path)}:{stage.from_line}: service target '{stage.name}' "
            f"has {len(probe_lines)} probe_dependencies.sh invocation(s), "
            f"expected exactly 1"
        )
        probe_line = probe_lines[0]
        arg_lines = _arg_lines(stage.body)
        assert (probe_line - 1) in arg_lines, (
            f"{_rel(path)}:{probe_line}: the probe call in service target "
            f"'{stage.name}' is not immediately preceded (line "
            f"{probe_line - 1}) by 'ARG DEPENDENCY_PACKAGES'"
        )


@pytest.mark.parametrize("path", PACK_DOCKERFILES, ids=_rel)
def test_no_file_level_dependency_packages_arg(path: Path):
    """Invariant 5: no file-level (pre-first-FROM) `ARG DEPENDENCY_PACKAGES`.

    A file-level ARG would make every whitelist edit invalidate the Docker build
    cache for the entire file, not just the probe step.
    """
    parsed = PARSED[path]
    bad_lines = _arg_lines(parsed.preamble)
    assert not bad_lines, (
        f"{_rel(path)}: found file-level 'ARG DEPENDENCY_PACKAGES' before the "
        f"first FROM at line(s) {bad_lines} -- this invalidates the cache for "
        f"every stage in the file on every whitelist edit; declare it inside "
        f"each service target instead, immediately before the probe RUN"
    )


@pytest.mark.parametrize("path", PACK_DOCKERFILES, ids=_rel)
def test_probe_call_is_last_build_step_in_its_stage(path: Path):
    """Invariant 6: the probe call is the last RUN/COPY/ADD in its stage.

    The probe's mount cache key covers the script's content, which every backend
    shares, so keeping it last makes editing the script cost a re-probe rather
    than a rebuild of the business layers above it.
    """
    parsed = PARSED[path]
    for stage in _service_targets(parsed):
        probe_lines = _probe_lines(stage.body)
        if not probe_lines:
            continue  # already reported by test_probe_call_count_and_arg_placement
        probe_line = probe_lines[0]
        for ln, text in stage.body:
            if ln <= probe_line:
                continue
            stripped = text.strip()
            m = BUILD_STEP_RE.match(stripped)
            if m:
                pytest.fail(
                    f"{_rel(path)}:{ln}: found a '{m.group(1).upper()}' "
                    f"instruction after the probe call (line {probe_line}) in "
                    f"service target '{stage.name}' -- the probe must be the "
                    f"last build step in its stage",
                )


def test_every_buildable_target_is_wired():
    """Aggregate sanity check: total wired targets == total buildable targets.

    The count is deliberately not hardcoded, so a new matrix rule grows the
    denominator on its own rather than failing on a stale magic number.
    """
    unwired = []
    for path, service in BUILD_TARGETS:
        parsed = PARSED[path]
        if parsed.stage(service) is None:
            unwired.append(f"{_rel(path)}: no '{service}' stage")
        elif parsed.stage(f"{service}-deps") is None:
            unwired.append(f"{_rel(path)}: '{service}' has no '{service}-deps' stage")
    assert not unwired, (
        f"{len(unwired)} of {len(BUILD_TARGETS)} buildable target(s) across "
        f"{len(PACK_DOCKERFILES)} Dockerfile(s) are not wired for dependency "
        f"probing: {unwired}"
    )
