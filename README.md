# GPUStack Runner

This repository serves as the Docker image pack center for GPUStack Runner.
It provides a collection of Dockerfiles to build images for various inference services across different accelerated
backends.

## Agenda

- [Onboard Services](#onboard-services)
- [Directory Structure](#directory-structure)
- [Dockerfile Convention](#dockerfile-convention)
- [Docker Image Naming Convention](#docker-image-naming-convention)
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

> [!WARNING]
> - The Atlas 300I series is currently experimental in vLLM, only supporting eager mode and float16 data type. And there
    are some known issues for running vLLM, you can refer to
    vllm-ascend [#3316](https://github.com/vllm-project/vllm-ascend/issues/3316)
    and [#2795](https://github.com/vllm-project/vllm-ascend/issues/2795).

| CANN Version <br/> (Variant) | MindIE    | vLLM                              | SGLang                 |
|------------------------------|-----------|-----------------------------------|------------------------|
| 8.5 (A3/910C)                | `2.3.0`   | `0.14.1`, `0.13.0`                | `0.5.8`                |
| 8.5 (910B)                   | `2.3.0`   | `0.14.1`, `0.13.0`                | `0.5.8`                |
| 8.5 (310P)                   | `2.3.0`   | `0.14.1`                          |                        |
| 8.3 (A3/910C)                | `2.2.rc1` | `0.12.0`, `0.11.0`                | `0.5.7`, `0.5.6.post2` |
| 8.3 (910B)                   | `2.2.rc1` | `0.12.0`, `0.11.0`                | `0.5.7`, `0.5.6.post2` |
| 8.3 (310P)                   | `2.2.rc1` |                                   |                        |
| 8.2 (A3/910C)                | `2.1.rc2` | `0.10.2`                          | `0.5.2`, `0.5.1.post3` |
| 8.2 (910B)                   | `2.1.rc2` | `0.10.2`, `0.10.0`,  <br/>`0.9.2` | `0.5.2`, `0.5.1.post3` |
| 8.2 (310P)                   | `2.1.rc2` | `0.10.0`, `0.9.2`                 |                        |

### Iluvatar CoreX

| CoreX Version <br/> (Variant) | vLLM    |
|-------------------------------|---------|
| 4.2                           | `0.8.3` |

### NVIDIA CUDA

> [!NOTE]
> - CUDA 12.9 supports Compute Capabilities:
    `7.5 8.0+PTX 8.9 9.0 10.0 10.3 12.0 12.1+PTX`.
> - CUDA 12.8 supports Compute Capabilities:
    `7.5 8.0+PTX 8.9 9.0 10.0+PTX 12.0+PTX`.
> - CUDA 12.6/12.4 supports Compute Capabilities:
    `7.5 8.0+PTX 8.9 9.0+PTX`.

| CUDA Version <br/> (Variant) | vLLM                                                                 | SGLang                                              | VoxBox   |
|------------------------------|----------------------------------------------------------------------|-----------------------------------------------------|----------|
| 12.9                         | `0.15.0`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`           | `0.5.8`, `0.5.7`, <br/>`0.5.6.post2`                |          |
| 12.8                         | `0.15.0`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2` | `0.5.8`, `0.5.7`, <br/>`0.5.6.post2`, `0.5.5.post3` | `0.0.21` |
| 12.6                         | `0.15.0`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2` |                                                     | `0.0.21` |

### Hygon DTK

| DTK Version <br/> (Variant) | vLLM                       |
|-----------------------------|----------------------------|
| 25.04                       | `0.11.0`, `0.9.2`, `0.8.5` |

### T-Head HGGC

| HGGC Version <br/> (Variant) | vLLM     | SGLang  |
|------------------------------|----------|---------|
| 12.3                         | `0.11.1` | `0.5.5` |

### MetaX MACA

| MACA Version <br/> (Variant) | vLLM     | SGLang  |
|------------------------------|----------|---------|
| 3.3                          | `0.11.2` | `0.5.6` |
| 3.2                          | `0.10.2` |         |
| 3.0                          | `0.9.1`  |         |

### MThreads MUSA

| MUSA Version <br/> (Variant) | vLLM    | SGLang  |
|------------------------------|---------|---------|
| 4.3.2                        |         | `0.5.2` |
| 4.1.0                        | `0.9.2` |         |

### AMD ROCm

> [!NOTE]
> - ROCm 7.0 supports LLVM targets:
    `gfx908 gfx90a gfx942 gfx950 gfx1030 gfx1100 gfx1101 gfx1200 gfx1201 gfx1150 gfx1151`.
> - ROCm 6.4 supports LLVM targets:
    `gfx908 gfx90a gfx942 gfx1030 gfx1100`.

> [!WARNING]
> - ROCm 7.0 vLLM `0.11.2` are reusing the official ROCm 6.4 PyTorch 2.9 wheel package rather than a ROCm
    7.0 specific PyTorch build. Although supports ROCm 7.0 in vLLM `0.11.2`, `gfx1150/gfx1151` are not supported yet.
> - ROCm 6.4 vLLM `0.13.0` supports `gfx903 gfx90a gfx942` only.
> - ROCm 6.4 SGLang supports `gfx942` only.
> - ROCm 7.0 SGLang supports `gfx950` only.

| ROCm Version <br/> (Variant) | vLLM                                                                 | SGLang                                              |
|------------------------------|----------------------------------------------------------------------|-----------------------------------------------------|
| 7.0                          | `0.15.0`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`           | `0.5.8`, `0.5.7`, <br/>`0.5.6.post2`                |
| 6.4                          | `0.15.0`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2` | `0.5.8`, `0.5.7`, <br/>`0.5.6.post2`, `0.5.5.post3` |

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

## Integration Process

### Ingesting a New Accelerated Backend

To add support for a new accelerated backend:

1. Create a new directory under `pack/` named with the new backend.
2. Add a `Dockerfile` in the new directory following the [Dockerfile Convention](#dockerfile-convention).
3. Update [pack.yml](.github/workflows/pack.yml), [discard.yml](.github/workflows/discard.yml) and [prune.yml](.github/workflows/prune.yml) to include the new backend in the build matrix.
4. Update [matrix.yml](pack/matrix.yaml) to include the new backend and its variants.
5. Update `_RE_DOCKER_IMAGE` in [runner.py](gpustack_runner/runner.py) to recognize the new backend.
6. [Optional] Update [tests](tests/gpustack_runner) if necessary.

### Ingesting a New Inference Service

To add support for a new inference service:

1. Modify the `Dockerfile` of the relevant backend in `pack/{BACKEND}/Dockerfile` to include the new service.
2. Update [pack.yml](.github/workflows/pack.yml) to include the new service in the build matrix.
3. Update [matrix.yml](pack/matrix.yaml) to include the new service.
4. Update `_RE_DOCKER_IMAGE` in [runner.py](gpustack_runner/runner.py) to recognize the new service.
5. [Optional] Update [tests](tests/gpustack_runner) if necessary.

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
