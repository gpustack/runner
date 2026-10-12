---
name: runner-release
description: Align the public support documentation (README.md, docs/supported-runners.md) with the published support records and the measured catalog when preparing a release or after Pack publishes new images.
---

# Runner release

Keep the public support tables truthful at release time.
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

## Cross-check first

Before editing, verify every `published` row against the catalog:

- a non-deprecated catalog entry exists on every platform the row lists;
- the entry's `service_version` equals the row's Engine;
- for CANN vLLM, the entry's `vllm-ascend` dependency equals the row's Plugin, suffix included.

A mismatch means the record or the catalog is stale. Stop and report it; do not align docs to a
record the catalog contradicts.

## Align README.md

The `### Supported runners` table shows the newest supported engine with its runtime line, as
`` `<engine>` (<runtime>) `` per cell.

- Recompute each cell from the `published` rows: highest engine version, then its runtime line.
- The cell carries the same `(rc)` mark as the historical table when the newest published CANN
  vLLM plugin is a prerelease, e.g. `` `0.27.1`(rc) (9.1) ``; the note below the table defines it.
- A backend/service with no published record keeps its historical-newest cell; do not blank it.
- MindIE and VoxBox have no published records; their cells track the historical tables.

## Align docs/supported-runners.md

The historical tables list every supported version, newest first, one row per runtime line and
variant.

- Add each newly published version at the head of its backend/runtime cell.
- Wrap a cell every two versions with `<br/>`, e.g. `` `0.31.0`, `0.30.0`,<br/> `0.29.0`, `0.27.1` ``;
  an odd tail version closes the cell without a trailing break.
- Mark a CANN vLLM version whose plugin is a prerelease with `(rc)`, e.g. `` `0.27.1`(rc) ``; the
  exact plugin identity stays in `docs/support-records.md`.
- When a version loses support, delete it from the cell; never mark it with strikethrough or bold.
- Platforms and exact plugin versions belong to `docs/support-records.md`, not to these tables.

## Verify

```sh
uv run mkdocs build --strict
uv run pre-commit run --files README.md docs/supported-runners.md --show-diff-on-failure
```

Then confirm each newly published Engine version appears in the matching historical cell and the
README cell it heads.

## Scope

This skill covers documentation alignment only. Image production is Pack
(`docs/packaging.md`); proposal and revision automation is auto-sync
(`docs/release-automation.md`); the PyPI release itself runs from `.github/workflows/release.yml`
on a pushed `v*.*.*` tag. Do not tag a release to publish docs alignment — docs paths are ignored
by the release trigger.
