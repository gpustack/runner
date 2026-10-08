# GPUStack Runner

This repository serves as the Docker image pack center for GPUStack Runner.
It provides a collection of Dockerfiles to build images for various inference services across different accelerated
backends.

## Agenda

- [Onboard Services](#onboard-services)
- [Directory Structure](#directory-structure)
- [Dockerfile Convention](#dockerfile-convention)
- [Docker Image Naming Convention](#docker-image-naming-convention)
- [Dependency Versions](#dependency-versions)
- [Integration Process](#integration-process)

## Onboard Services

> [!TIP]
> - The list below shows the accelerated backends and inference services available in the latest release. For support of
    backends or services not shown here, please refer to previous release tags.
> - Deprecated inference service versions in the latest release are marked with ~~strikethrough~~ formatting. They may
    still be available in previous releases, and not recommended for new deployments.
> - Polished inference service versions in the latest release are marked with **bold** formatting. If they are using in
    your deployment, it is recommended to pull the latest images and upgrade.

The following table lists the supported accelerated backends and their corresponding inference services with versions.

### Ascend CANN

| CANN Version <br/> (Variant) | MindIE    | vLLM                                                                                 | SGLang                                      |
|------------------------------|-----------|--------------------------------------------------------------------------------------|---------------------------------------------|
| 9.1 (950/A5)                 |           | **`0.23.0`**                                                                         |                                             |
| 9.1 (A3/910C)                |           | **`0.23.0`**                                                                         |                                             |
| 9.1 (910B)                   |           | **`0.23.0`**                                                                         |                                             |
| 9.1 (310P)                   |           | **`0.23.0`**                                                                         |                                             |
| 9.0 (A3/910C)                |           | `0.20.2`(rc)                                                                         | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`     |
| 9.0 (910B)                   |           | `0.20.2`(rc)                                                                         | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`     |
| 9.0 (310P)                   |           | `0.20.2`(rc)                                                                         |                                             |
| 8.5 (A3/910C)                | `2.3.0`   | `0.18.0`, `0.17.0`(rc), <br/>`0.16.0`(rc), `0.15.0`(rc), <br/>`0.14.1`(rc), `0.13.0` | `0.5.12.post1`, <br/>`0.5.9`, `0.5.8.post1` |
| 8.5 (910B)                   | `2.3.0`   | `0.18.0`, `0.17.0`(rc), <br/>`0.16.0`(rc), `0.15.0`(rc), <br/>`0.14.1`(rc), `0.13.0` | `0.5.12.post1`, <br/>`0.5.9`, `0.5.8.post1` |
| 8.5 (310P)                   | `2.3.0`   | `0.18.0`, `0.17.0`(rc), <br/>`0.16.0`(rc), `0.15.0`(rc), <br/>`0.14.1`(rc)           |                                             |
| 8.3 (A3/910C)                | `2.2.rc1` | `0.12.0`(rc), `0.11.0`                                                               | `0.5.7`, `0.5.6.post2`                      |
| 8.3 (910B)                   | `2.2.rc1` | `0.12.0`(rc), `0.11.0`                                                               | `0.5.7`, `0.5.6.post2`                      |
| 8.3 (310P)                   | `2.2.rc1` |                                                                                      |                                             |
| 8.2 (A3/910C)                | `2.1.rc2` | `0.10.2`(rc)                                                                         |                                             |
| 8.2 (910B)                   | `2.1.rc2` | `0.10.2`(rc), `0.10.0`(rc),  <br/>`0.9.1`                                            |                                             |
| 8.2 (310P)                   | `2.1.rc2` | `0.10.0`(rc), `0.9.1`                                                                |                                             |

### Iluvatar CoreX

| CoreX Version <br/> (Variant) | vLLM    |
|-------------------------------|---------|
| 4.2                           | `0.8.3` |

### NVIDIA CUDA

| CUDA Version <br/> (Variant) | vLLM                                                                                                                                                                                                              | SGLang                                                                                                            | VoxBox   |
|------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|----------|
| 13.0                         | **`0.30.0`**, **`0.29.0`**, **`0.27.1`**,<br/> **`0.25.1`**, **`0.24.0`**,<br/> `0.22.1`, `0.21.0`,<br/> `0.20.2`, `0.19.1`,<br/> `0.18.1`                                                                                      | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`, `0.5.12.post1`                                                           |          |
| 12.9                         | **`0.30.0`**, **`0.29.0`**, **`0.27.1`**,<br/> **`0.25.1`**, **`0.24.0`**,<br/> `0.22.1`, `0.21.0`,<br/> `0.20.2`, `0.19.1`,<br/> `0.18.1`, `0.17.1`,<br/> `0.16.0`, `0.15.1`,<br/> `0.14.1`, `0.13.0`,<br/> `0.12.0`, `0.11.2` | `0.5.18`, `0.5.15.post1`,<br/> `0.5.14`, `0.5.12.post1`, <br/>`0.5.9`, `0.5.8.post1`, <br/>`0.5.7`, `0.5.6.post2` |          |
| 12.8                         | `0.17.1`, `0.16.0`, <br/>`0.15.1`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2`                                                                                                                     | `0.5.9`, `0.5.8.post1`, <br/>`0.5.7`, `0.5.6.post2`, <br/>`0.5.5.post3`                                           | `0.0.21` |
| 12.6                         | `0.15.1`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2`                                                                                                                                              |                                                                                                                   | `0.0.21` |

### Hygon DTK

| DTK Version <br/> (Variant) | vLLM                                      | SGLang       |
|-----------------------------|-------------------------------------------|--------------|
| 26.04                       | **`0.18.1`**                              | `0.5.10`(rc) |
| 25.04                       | `0.18.1`, `0.11.0`,<br/> `0.9.2`, `0.8.5` |              |

### T-Head HGGC

| HGGC Version <br/> (Variant) | vLLM                                        | SGLang                           |
|------------------------------|---------------------------------------------|----------------------------------|
| 13.0                         | `0.23.0`, `0.20.1`,<br/> `0.19.0`, `0.18.0` | `0.5.12`, `0.5.10`,<br/> `0.5.9` |
| 12.3                         | `0.12.0`, `0.11.1`                          | `0.5.6`, `0.5.5`                 |

### MetaX MACA

| MACA Version <br/> (Variant) | vLLM               | SGLang             |
|------------------------------|--------------------|--------------------|
| 3.7                          | `0.21.0`, `0.20.0` | `0.5.11`, `0.5.10` |
| 3.5                          | `0.14.0`           | `0.5.9`            |
| 3.3                          | `0.11.2`           | `0.5.6`            |
| 3.2                          | `0.10.2`           |                    |
| 3.0                          | `0.9.1`            |                    |

### MThreads MUSA

| MUSA Version <br/> (Variant) | vLLM    | SGLang  |
|------------------------------|---------|---------|
| 4.3.2                        |         | `0.5.7` |
| 4.1.0                        | `0.9.2` |         |

### AMD ROCm

| ROCm Version <br/> (Variant) | vLLM                                                                                                          | SGLang                                                    |
|------------------------------|---------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------|
| 7.2                          | **`0.30.0`**, **`0.29.0`**, **`0.27.1`**,<br/> **`0.25.1`**, **`0.24.0`**,<br/> `0.22.1`, `0.21.0`,<br/> `0.20.2`, `0.19.1` | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`, `0.5.12.post1`   |
| 7.1                          | `0.17.1`                                                                                                      |                                                           |
| 7.0                          | `0.18.1`, `0.16.0`,<br/> `0.15.1`, `0.14.1`,<br/> `0.13.0`, `0.12.0`,<br/> `0.11.2`                           | `0.5.9`, `0.5.8.post1`, <br/>`0.5.7`, `0.5.6.post2`       |
| 6.4                          | `0.16.0`, `0.15.1`,<br/> `0.14.1`, `0.13.0`,<br/> `0.12.0`, `0.11.2`,<br/> `0.10.2`                           | `0.5.8.post1`, `0.5.7`, <br/>`0.5.6.post2`, `0.5.5.post3` |

## Directory Structure

The pack skeleton is organized by backend:

```text
pack
├── {BACKEND 1}
│   └── Dockerfile
├── {BACKEND 2}
│   └── Dockerfile
├── {BACKEND 3}
│   └── Dockerfile
├── ...
│   └── Dockerfile
└── {BACKEND N}
    └── Dockerfile

```

## Dockerfile Convention

Each Dockerfile follows these conventions:

- Begin with comments describing the package logic in steps and usage of build arguments (`ARG`s).
- Use `ARG` for all required and optional build arguments. If a required argument is unused, mark it as `(PLACEHOLDER)`.
- Use heredoc syntax for `RUN` commands to improve readability.

### Example Dockerfile Structure

```dockerfile

# Describe package logic and ARG usage.
#
ARG PYTHON_VERSION=...                                 # REQUIRED
ARG CMAKE_MAX_JOBS=...                                 # REQUIRED
ARG {OTHERS}                                           # OPTIONAL
ARG {BACKEND}_VERSION=...                              # REQUIRED
ARG {BACKEND}_VERSION_EXTRA=...                        # OPTIONAL
ARG {BACKEND}_ARCHS=...                                # REQUIRED
ARG {BACKEND}_{OTHERS}=...                             # OPTIONAL
ARG {SERVICE}_BASE_IMAGE=...                           # REQUIRED
ARG {SERVICE}_VERSION=...                              # REQUIRED
ARG {SERVICE}_{OTHERS}=...                             # OPTIONAL
ARG {SERVICE}_{FRAMEWORK}_VERSION=...                  # REQUIRED
ARG {SERVICE}_{FRAMEWORK}_{OTHERS}=...                 # OPTIONAL

# Stage Bake Runtime
FROM {BACKEND DEVEL IMAGE} AS runtime
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG ...
RUN <<EOF
    # TODO: install runtime dependencies
EOF

# Stage Install Service
FROM {BACKEND}_BASE_IMAGE AS {service}
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG ...
RUN <<EOF
    # TODO: install service and dependencies
EOF

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

```

### Example Build Command

Each Dockerfile is built with the backend directory as its build context:

```bash
cd pack/cuda

docker buildx build \
  --file Dockerfile.vllm \
  --target vllm \
  --build-context shared=../shared \
  --build-arg DEPENDENCY_PACKAGES="$(jq -er '[.[][]] | join(" ")' ../dependencies.json)" \
  --tag gpustack/runner:cuda13.0-vllm0.29.0 \
  .
```

Two of these flags are mandatory and one is optional:

- `--target {SERVICE}` is **mandatory**. Every Dockerfile ends with an export-only
  `FROM scratch AS {SERVICE}-deps` stage that carries nothing but the probed dependency manifest. Without
  `--target`, Docker builds the *last* stage in the file and hands back an empty image.
- `--build-context shared=../shared` is **mandatory** as well. The dependency probe script lives in
  [pack/shared](pack/shared) so that all backends share one copy, and the build context of `pack/{BACKEND}/`
  cannot reach it with a plain `COPY`; a named build context is the only way in. Omitting the flag makes the
  `RUN --mount=type=bind,from=shared` step resolve `shared` as an image name and fail the build.
- `--build-arg DEPENDENCY_PACKAGES=...`, in contrast, is optional and is the escape hatch for manual local
  builds. Leaving it empty skips probing, and the resulting image then has **no**
  `/etc/gpustack-runner/dependencies.json` — which is also how the data pipeline tells "never probed" apart
  from "probed, nothing installed".

## Docker Image Naming Convention

The Docker image naming convention is as follows:

- Multi-architecture image names: `{NAMESPACE}/{REPOSITORY}:{TAG}`.
- Single-architecture image tags:
  `{BACKEND}{BACKEND_VERSION%.*}[-{BACKEND_VARIANT}]-{SERVICE}{SERVICE_VERSION}-{OS}-{ARCH}`.
- Multi-architecture image tags: `{BACKEND}{BACKEND_VERSION%.*}[-{BACKEND_VARIANT}]-{SERVICE}{SERVICE_VERSION}[-dev]`.
- All names adn tags must be lowercase.

### Example

- NAMESPACE: `gpustack`
- REPOSITORY: `runner`

| Accelerated Backend | OS/ARCH     | Inference Service | Single-Arch Image Name                                | Multi-Arch Image Name                     |
|---------------------|-------------|-------------------|-------------------------------------------------------|-------------------------------------------|
| Ascend CANN 910b    | linux/amd64 | vLLM              | `gpustack/runner:cann8.1-910b-vllm0.9.2-linux-amd64`  | `gpustack/runner:cann8.1-910b-vllm0.9.2`  |
| Ascend CANN 910b    | linux/arm64 | vLLM              | `gpustack/runner:cann8.1-910b-vllm0.9.2-linux-arm64`  | `gpustack/runner:cann8.1-910b-vllm0.9.2`  |
| NVIDIA CUDA 12.8    | linux/amd64 | vLLM              | `gpustack/runner:cuda12.8-910b-vllm0.9.2-linux-amd64` | `gpustack/runner:cuda12.8-910b-vllm0.9.2` |
| NVIDIA CUDA 12.8    | linux/arm64 | vLLM              | `gpustack/runner:cuda12.8-910b-vllm0.9.2-linux-arm64` | `gpustack/runner:cuda12.8-910b-vllm0.9.2` |

### Build and Release Workflow

1. Build single architecture images for OS/ARCH, e.g. `gpustack/runner:cann8.1-910b-vllm0.9.2-linux-amd64`.
2. Combine single-architecture images into a multiple architectures image, e.g.
   `gpustack/runner:cann8.1-910b-vllm0.9.2-dev`.
3. After testing, rename the multi-architecture image to the final tag, e.g. `gpustack/runner:cann8.1-910b-vllm0.9.2`.

## Dependency Versions

Besides the image tag, each entry of [runner.py.json](gpustack_runner/runner.py.json) may carry a
`dependencies` map, which records the versions of a whitelisted set of Python packages **as actually
installed in the built image**, not as declared by the Dockerfile `ARG`s. The whitelist lives in
[pack/dependencies.json](pack/dependencies.json) and the probe runs at build time.

```json
{
  "docker_image": "gpustack/runner:cann9.1-a3-vllm0.23.0",
  "dependencies": {
    "lmcache": "0.4.3",
    "lmcache-ascend": "0.4.3",
    "ray": "2.54.0",
    "torch": "2.10.0",
    "torch-npu": "2.10.0rc1",
    "vllm-ascend": "0.23.0"
  }
}
```

### One Name, Several Distributions

Keys are the dependency names of the whitelist. Most map one to one onto a distribution, but a name may
cover several, highest priority first:

```json
{
  "mooncake-transfer-engine": [
    "mooncake-transfer-engine-npu",
    "mooncake-transfer-engine-rocm",
    "mooncake-transfer-engine"
  ]
}
```

The probe reports raw distribution names, and `pack/merge_runner.sh` folds them onto the dependency name —
the first distribution of the list that is installed wins — so a consumer asking about
`mooncake-transfer-engine` never has to know the accelerator naming conventions.

Two conditions must both hold before grouping distributions under one name:

1. **They must be mutually exclusive** — at most one of them can be installed in any given image. Folding
   keeps a single winner, so grouping distributions that *coexist* silently discards one of them. `torch`
   and `torch-npu` look like such a pair by their names, but `torch-npu` pins `torch==<same version>` and is
   the NPU backend *on top of* it: both are installed, with different versions that mean different things.
   The same holds for `lmcache` and `lmcache-ascend` — a CANN image carries both, and they do not even track
   the same version.
2. **Their versions must be comparable** — the same versioning scheme, ideally the same release line. A
   grouped name yields one specifier for all of them, so a specifier that is meaningful for one and
   meaningless for another gives a confidently wrong answer. `sglang-kernel` and `sgl-kernel-npu` *are*
   mutually exclusive, yet they stay separate: the former is `0.4.6.post1` and the latter is a date version
   `2026.6.1`, so `>=0.4.5` would match the NPU build for no reason at all.

`mooncake-transfer-engine` satisfies both, which is why it is the one grouped entry: its `-npu`, `-rocm` and
generic builds are one per platform and share a release line (`0.3.11.post1` / `0.3.10.post2`).

When in doubt, give each distribution its own name. That records both facts and asserts nothing.

The raw, unfolded probe result stays inside the image at `/etc/gpustack-runner/dependencies.json`, so
`docker run --rm <image> cat /etc/gpustack-runner/dependencies.json` still shows every distribution and
version for troubleshooting.

### Absent Field vs. Absent Key

The field has two levels of meaning, and conflating them leads to wrong conclusions:

| State                                 | Meaning                                                                                       |
|---------------------------------------|-----------------------------------------------------------------------------------------------|
| `dependencies` is absent              | The image was **never probed** — built before probing existed, or built without the whitelist |
| `dependencies` is a map missing a key | The image **was** probed and the package is **not installed**                                 |

### Querying

All three query entries — `list_runners`, `list_backend_runners` and `list_service_runners` — accept a
`dependencies` argument: a tuple of `(dependency name, PEP 440 specifier)` pairs, matched directly against
the `dependencies` map of each entry.

```python
# Images whose lmcache is new enough.
list_runners(service="vllm", dependencies=(("lmcache", ">=0.4.6"),))

# Multiple conditions.
list_runners(backend="cuda", dependencies=(("lmcache", ">=0.4.6"), ("torch", ">=2.9"),))

# An empty specifier asks only whether the package is installed.
list_runners(backend="cuda", dependencies=(("vllm-omni", ""),))

# Strict mode: drop images that were never probed.
list_runners(
    backend="cuda",
    dependencies=(("lmcache", ">=0.4.6"),),
    with_unknown_dependencies=False,
)
```

Five behaviors to keep in mind:

1. **Conditions are ANDed.** A runner must satisfy every pair to be returned; there is no "any of" form.
2. **Unprobed runners are kept by default.** A runner without a `dependencies` field is never filtered out by
   a dependency condition, so that adding a condition does not make every pre-existing image disappear at
   once. Pass `with_unknown_dependencies=False` to tighten this to "only runners known to satisfy the
   condition" — expect a much shorter list until the fleet has been rebuilt.
3. **Pre-releases match.** Matching is done with `prereleases=True`, because `rc` versions are routine here
   (`vllm-ascend 0.20.2rc1`, `sglang 0.5.10rc0`); without it `>=0.20.0` would silently skip `0.20.2rc1`. Note
   the converse, which is **not** a bug: `>=0.4.6` does not match `0.4.6rc1`, because PEP 440 orders
   `0.4.6rc1 < 0.4.6`. The same rule applies to `dev` versions — `0.27.0rc2.dev25+g<sha>` does not satisfy
   `>=0.27.0`. Write the bound you actually mean (`>=0.4.6rc1`) instead of "fixing" the comparison.
4. **An empty specifier is a pure existence check.** `("vllm-omni", "")` matches any image that has the
   package, whatever its version. This is the right form for a package installed from a commit, whose
   version string carries no information — comparing it would give a confidently wrong answer.
5. **An unknown name matches nothing; it does not raise.** The whitelist is a build-side file and is not
   shipped with the library, so there is nothing to check a name against. A misspelled name simply yields an
   empty result, which is indistinguishable from "no image qualifies" — callers own their spelling.

## Integration Process

### Ingesting a New Accelerated Backend

To add support for a new accelerated backend:

1. Create a new directory under `pack/` named with the new backend.
2. Add a `Dockerfile` in the new directory following the [Dockerfile Convention](#dockerfile-convention).
3. Update [pack.yml](.github/workflows/pack.yml), [discard.yml](.github/workflows/discard.yml)
   and [prune.yml](.github/workflows/prune.yml) to include the new backend in the build matrix.
4. Update [matrix.yml](pack/matrix.yaml) to include the new backend and its variants.
5. Update `_RE_DOCKER_IMAGE` in [runner.py](gpustack_runner/runner.py) to recognize the new backend.
6. [Optional] Update [tests](tests/gpustack_runner) if necessary.

### Ingesting a New Inference Service

To add support for a new inference service:

1. Modify the `Dockerfile` of the relevant backend in `pack/{BACKEND}/Dockerfile` to include the new service.
2. Update [pack.yml](.github/workflows/pack.yml) to include the new service in the build matrix.
3. Update [matrix.yml](pack/matrix.yaml) to include the new service.
4. Update `_RE_DOCKER_IMAGE` in [runner.py](gpustack_runner/runner.py) to recognize the new service.
5. Review [pack/dependencies.json](pack/dependencies.json) for the key packages the new service brings
   in. A package that is not listed there is never probed for any image, and consumers have no way to ask
   about it. The bar for listing one is **it directly decides whether a model or the inference backend
   starts** *and* **it is updated often or breaks compatibility** — every entry is recorded for every image,
   so the list is meant to stay short. Before grouping accelerator-specific variants under one name, confirm
   they are mutually exclusive — see [One Name, Several Distributions](#one-name-several-distributions);
   when in doubt, give each its own name, which records both facts and asserts nothing.
6. [Optional] Update [tests](tests/gpustack_runner) if necessary.

## License

Copyright (c) 2025 The GPUStack authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at [LICENSE](./LICENSE) file for details.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
