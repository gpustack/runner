# Packaging

This guide describes how GPUStack runner images are built: which file defines a service, how the
build matrix expands, how single-platform images are promoted to a multi-platform tag, and where
the recorded evidence for each image comes from.

Most steps below run in the `Pack` workflow (`.github/workflows/pack.yml`). `make package` covers
local image builds only.

## Service file ownership

Each accelerated backend owns its own directory under `pack/`, for example `pack/cuda/` or
`pack/cann/`. A service is defined by a separate file named `Dockerfile.{service}`, so a
backend that ships several services owns one file per service:

```text
pack/{backend}/Dockerfile.{service}
```

`pack/resolve_dockerfile.sh` resolves a `(backend, service)` pair to exactly one file. It
fails with an error when the resolved path does not exist — a build never silently falls back
to an unrelated service.

### Selected stage and historical exception

The build target is the service name, so `pack/{backend}/Dockerfile.{service}` must define a
stage of that name. That stage is the final image for the service, and `make package` passes
it to `docker buildx build --target`.

There is one historical exception. For an explicitly requested post operation, the resolver first
looks under `pack/.post_operation/<operation>/`. If `pack/.post_operation/<operation>/<backend>/Dockerfile.<service>`
is absent, the combined filename `pack/.post_operation/<operation>/<backend>/Dockerfile` is
accepted as a fallback. Those operations predate the per-service layout; new services always use
the per-service filename.

The rule lives in one place — the resolver — so both the matrix expansion and the build read
the same decision:

```sh
pack/resolve_dockerfile.sh <pack directory> <backend> <service> [post operation]
```

## Build matrix

`pack/matrix.yaml` is the source of the build matrix. Each rule names a `backend`, the
`services` it supports, and optional per-platform `platforms` and build `args`.
CUDA/VoxBox and CANN/MindIE have explicit rules for their existing published runtime and platform combinations.

`pack/expand_matrix.sh` turns those rules into concrete build jobs:

1. Rules are filtered by backend and by the requested target service.
2. `ARG` defaults are read from the resolved Dockerfile and merged under the rule `args`.
3. Backend and service versions are split into major/minor components for tag construction.
4. Each surviving rule becomes one job per requested platform.

The tag is assembled from those parts, following the naming convention: a backend version with
its patch dropped, an optional backend variant, and the service with its full version. A `-dev`
suffix is appended unless the expansion is for a release. Everything is lowercased.

`make package` consumes the expanded jobs directly. Each job builds with
`--platform {platform}` and tags `{namespace}/{repository}:{platform_tag}`, with a buildx
builder named `gpustack` that supports emulation for foreign platforms.

## Native per-platform final-image collection by digest

Dependency metadata is collected on the native runner of each platform, from the final image,
addressed by digest. The receipt is recorded outside the image; it is not embedded in it.

- Each build job records its output with `record-build`, retaining the job identity, the
  attempt, the backend, the service, the platform, and the resulting `image_digest`.
- `collect-record` then runs on the native runner for that platform and produces one receipt
  per platform. Because collection happens natively, the probe reads the real service
  interpreter for that platform rather than emulating it.
- The digest, not the mutable tag, is what the receipt and the later manifest reference. A
  receipt therefore cannot be satisfied by a different image that happens to carry the same
  tag.

A partial rerun keeps the frozen invocation and selects the authoritative attempt per build.
The old receipt for a replaced attempt must be replaced too; duplicates are rejected, and a
stale receipt cannot validate against a replacement digest or attempt.

Collection is deliberately strict about evidence:

- A distribution without `Name` or `Version` metadata fails the probe.
- Two installed distributions normalizing to the same name with different versions fail.
- Enumerating zero distributions fails, because an empty environment is not evidence that a
  service lacks the selected packages.
- Explicitly disabled collection produces status `unknown` and carries no distributions.

## Correct Python environment

The collector must interrogate the interpreter that actually installed the service, not
whatever `python` happens to resolve to. Interpreter selection compares Python *environments*
rather than executable realpaths, because virtual environments commonly symlink one binary
while exposing different distribution metadata:

```text
sys.prefix, sysconfig.get_path("purelib"), sysconfig.get_path("platlib")
```

Candidates are checked in a fixed order: the active `VIRTUAL_ENV`, a known service virtual
environment (`/opt/venv` for ROCm SGLang, which must exist and be executable), then `python` and
`python3` from `PATH`. There is no way to pass an arbitrary interpreter; the known ROCm SGLang
environment is the only fixed one. If two candidates resolve to different identities, collection
fails as ambiguous rather than guessing. If a required environment is missing or no candidate is
usable, it fails as unavailable.

The probe itself reads distribution metadata through `importlib.metadata` without importing
service packages, so measurement cannot trigger package side effects or fail because a service
module is not importable outside its runtime context.

## Prepared and published promotion

This flow runs in `.github/workflows/pack.yml`. `make package` only performs local image builds: it
does not collect receipts or update the catalog, so a local build does not exercise centralized
collection.

Pack changes a support row from `prepared` to `published` only when measured results match its
engine, plugin, runtime, variant, and all declared platforms. This does not verify GPU runtime
compatibility.

1. Freeze. `freeze` binds the repository, the build jobs and the manifest jobs into a context,
   including digests over the parsed context and the mapping. Every later step reads this frozen
   context instead of re-deriving a matrix from artifacts.
2. Build and record. Each platform job retains its own Package output via `record-build`, then
   produces one receipt via `collect-record`.
3. Publish. `publish` validates the complete artifact set against the frozen context before
   creating digest-based manifests. It does not emit a manifest for an image whose evidence is
   missing or inconsistent.
4. Catalog. `catalog` rechecks the published manifests and folds only validated distributions
   into the catalog entry.
5. Merge. `pack/merge_runner.sh` merges the new entries into `gpustack_runner/runner.py.json` and
   promotes matching rows in the support document. Pack opens a pull request with those changes.

Missing data never means reuse. The merge path refuses to render output from an incomplete set
and refuses a catalog repository that differs from the frozen Pack context. A dedicated
catalog-refresh mode only prunes and discards existing rows and explicitly rejects build
inputs, so it cannot be used to bypass validation of changed images.

Support status is documented separately, including what `prepared` and `published` mean. See
[Supported runners](supported-runners.md).

Related: [Dependency metadata](dependency-metadata.md) covers how validated receipts become the
`dependencies` map of a runner entry.

## Recipe conventions

Start a new recipe with comments describing its packaging steps and build arguments.
Use `ARG` for required and optional build inputs. Mark an intentionally unused required argument as `(PLACEHOLDER)`.
Keep defaults visible to matrix expansion, and redeclare arguments in stages that use them.
Use heredoc syntax for multiline `RUN` commands, following the surrounding recipes.
State compatibility reasons beside the relevant version or patch.

The file is `pack/<backend>/Dockerfile.<service>`, with the backend directory as its build context.
Define the service's named final target and preserve its runtime ancestry, platform branches, and entrypoint.
Active recipes do not require dependency-probe arguments, shared mounts, embedded metadata, or export stages.
Pack collects dependencies from the final image through the central collector.

## Adding a backend or service

For a new backend, create its directory under `pack/` and one `Dockerfile.<service>` per supported service.
For a new service on an existing backend, add its own service file in that backend directory.
Do not extend a combined active Dockerfile.

1. Add supported combinations, platform coverage, variants, and argument overrides to `pack/matrix.yaml`.
2. Review backend choices in `.github/workflows/pack.yml`, `prune.yml`, and `discard.yml`.
   Add new backend choices where needed. Add new service target choices to Pack.
3. Update `_RE_DOCKER_IMAGE` in `gpustack_runner/runner.py` when the new backend or service needs parser support.
4. Review `pack/dependencies.json` for packages that determine engine startup or compatibility.
   Keep separate keys for packages that coexist or use incomparable versions; see [Dependency metadata](dependency-metadata.md).
5. Add explicit `prepared` support records with the intended platforms in [Supported runners](supported-runners.md).
6. Add behavior tests for image parsing, recipe selection, matrix expansion, and relevant dependency behavior.
   Run `uv run pytest tests/gpustack_runner tests/pack` and `uv run mkdocs build --strict`.

Maintainers review the source changes before Pack builds and collects the new images.
Local build success alone does not establish catalog measurement, published support, or GPU runtime compatibility.
