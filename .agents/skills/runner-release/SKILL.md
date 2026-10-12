---
name: runner-release
description: Cut a gpustack-runner package release end to end (select and push the tag, curate the GitHub Release notes, promote), and align the public support documentation (README.md, docs/supported-runners.md) with published support records after Pack publishes images.
---

# Runner release

Two maintainer duties:

1. **Cut a package release** — push a version tag; `release.yml` builds and publishes it.
2. **Align support docs** — after Pack publishes images, realign `README.md` and
   `docs/supported-runners.md` with the published records.

## Cut a package release

The git tag is the single source of truth: hatch-vcs derives the package version from it at build
time, and there is no version file to bump. Pushing a `v*.*.*` tag runs
`.github/workflows/release.yml`: build the distributions, create the GitHub Release as a
**pre-release** with a generated baseline note and the wheel/sdist assets, publish to PyPI, then
verify an isolated install. Branch pushes to `main` or `v*-dev` run the same job against TestPyPI
and create no release.

PyPI is the irreversible step: a version once published there cannot be re-uploaded or edited. The
pre-release gate therefore covers the GitHub Release only — promotion flips its visibility, never
the PyPI record.

### Hard rules

- Tag shapes: `vX.Y.Z` final, `vX.Y.ZrcN` pre-release, `vX.Y.Z.postN` post-release. PEP 440
  canonical spellings only; history contains a non-dotted `v0.1.27postN` — do not repeat it.
- A tag whose PyPI publish succeeded is burned. NEVER delete or move it; fix forward with a new
  version. Delete-and-recreate is limited to a tag that never reached PyPI and is interactive-only.
- An `rc` tag stays a pre-release; never promote it.
- Release from `origin/main` HEAD by default. A maintenance line (`v*-dev` branch) targets that
  branch's HEAD; flag the choice in the summary.
- Interactive mode confirms every mutating step (tag push, note replacement, promotion). Auto mode
  runs unattended and stops at the published pre-release: report its URL and let the user promote.

### 1. Preflight (read-only)

```sh
gh auth status
git fetch origin --tags --prune
git status --porcelain                            # must be empty
git tag -l 'v*' --sort=-v:refname | head -5
git rev-parse origin/main
```

### 2. Version and commit (confirm)

- Read the range since the previous tag: `git log --no-merges --oneline <last>..origin/main`.
- Propose the bump from the Conventional Commits in range: any `feat` → minor; fixes, docs, and
  chores → patch. Use `.postN` only to re-issue the same version line (packaging metadata or a
  docs-only rebuild of unchanged content).
- Confirm the (version, commit) pair before tagging.

### 3. Draft notes

Group the range by type: Features / Fixes / Docs / Other; omit empty sections. Keep highlights and
fold noisy `chore`/`ci`/`test` entries. Link PRs from `(#NNN)` subjects. Do not open the body with
a heading that repeats the tag. End with the Full Changelog compare URL
(`https://github.com/gpustack/runner/compare/<last>...<VER>`). This draft replaces the generated
baseline once the run is green.

### 4. Tag and monitor (confirm, then read-only)

```sh
git tag -a "$VER" "$SHA" -m "Release $VER"
git push origin "$VER"
gh run list --branch "$VER" --limit 5     # the release.yml run for the tag
gh run watch <run-id> --exit-status       # background it; wait for the completion notification
```

The job's own verify step installs the published package from PyPI, so a green run proves PyPI
serves the new version. On failure read `gh run view <run-id> --log-failed`; retry the same run on
transient errors. If the failure is real and PyPI already holds the version, cut the next version
instead — never re-tag.

### 5. Curate notes and promote (confirm)

```sh
gh release view "$VER" --json body,isPrerelease     # inspect the baseline first
gh release edit "$VER" --notes-file notes.md
gh release edit "$VER" --prerelease=false --latest  # finals only
```

A maintenance-line final keeps `--latest=false` when a newer stable tag exists. Verify the badge
with `gh api repos/gpustack/runner/releases/latest --jq .tag_name`. Skip promotion for `rc` tags
and in auto mode.

## Align support docs

Two files face the reader: `README.md` (newest supported engine per backend/service) and
`docs/supported-runners.md` (historical tables of every supported version).
Both drift whenever Pack publishes images; realign them here.

Two sources of truth, in order:

1. `docs/support-records.md` — the machine-managed table between the
   `<!-- runner-support-records:start -->` / `:end -->` markers. Only `published` rows claim an
   image exists; `prepared` rows are merged proposals and never appear in the public tables.
2. `gpustack_runner/runner.py.json` — the measured catalog. Use it to cross-check, never to
   invent versions a record does not declare.

NEVER edit `docs/support-records.md` by hand; Pack owns it (see `tests/pack/test_merge_runner.py`).
NEVER list a version that no `published` record or historical entry supports.

### Cross-check first

Before editing, verify every `published` row against the catalog:

- a non-deprecated catalog entry exists on every platform the row lists;
- the entry's `service_version` equals the row's Engine;
- for CANN vLLM, the entry's `vllm-ascend` dependency equals the row's Plugin, suffix included.

A mismatch means the record or the catalog is stale. Stop and report it; do not align docs to a
record the catalog contradicts.

### Align README.md

The `### Supported runners` table shows the newest supported engine with its runtime line, as
`` `<engine>` (<runtime>) `` per cell.

- Recompute each cell from the `published` rows: highest engine version, then its runtime line.
- The cell carries the same `(rc)` mark as the historical table when the newest published CANN
  vLLM plugin is a prerelease, e.g. `` `0.27.1`(rc) (9.1) ``; the note below the table defines it.
- A backend/service with no published record keeps its historical-newest cell; do not blank it.
- MindIE and VoxBox have no published records; their cells track the historical tables.

### Align docs/supported-runners.md

The historical tables list every supported version, newest first, one row per runtime line and
variant.

- Add each newly published version at the head of its backend/runtime cell.
- Wrap a cell every two versions with `<br/>`, e.g. `` `0.31.0`, `0.30.0`,<br/> `0.29.0`, `0.27.1` ``;
  an odd tail version closes the cell without a trailing break.
- Mark a CANN vLLM version whose plugin is a prerelease with `(rc)`, e.g. `` `0.27.1`(rc) ``; the
  exact plugin identity stays in `docs/support-records.md`.
- When a version loses support, delete it from the cell; never mark it with strikethrough or bold.
- Platforms and exact plugin versions belong to `docs/support-records.md`, not to these tables.

### Verify

```sh
uv run mkdocs build --strict
uv run pre-commit run --files README.md docs/supported-runners.md --show-diff-on-failure
```

Then confirm each newly published Engine version appears in the matching historical cell and the
README cell it heads.

## Scope

Package releases and support-docs alignment run here. Image production is Pack
(`docs/packaging.md`); proposal and revision automation is auto-sync
(`docs/release-automation.md`). Docs-only changes never trigger a release: the release workflow
ignores docs paths on branch pushes, so docs alignment needs no tag.
