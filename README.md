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

The following table lists the supported accelerated backends and their corresponding inference services with versions.

### Ascend CANN

| CANN Version (Variant) | Inference Service (Version List)                                                                                                         |
|------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| 8.3 (A3/910C)          | vLLM: `0.11.0`                                                                                                                           |
| 8.2 (910B)             | vLLM: `0.11.0`                                                                                                                           |
| 8.2 (A3/910C)          | MindIE: `2.1.rc2` <br/> vLLM: `0.11.0`, `0.10.2`, `0.10.1.1`  <br/> SGLang:  `0.5.2`, `0.5.1.post3`                                      |
| 8.2 (910B)             | MindIE: `2.1.rc2`, `2.1.rc1` <br/> vLLM: `0.11.0`, `0.10.2`, `0.10.1.1`, `0.10.0`, `0.9.2`, `0.9.1` <br/> SGLang: `0.5.2`, `0.5.1.post3` |
| 8.2 (310P)             | MindIE: `2.1.rc2`, `2.1.rc1` <br/> vLLM: `0.10.2`, `0.10.1.1`, `0.10.0`, `0.9.2`                                                         |

### Iluvatar CoreX

| CoreX Version (Variant) | Inference Service (Version List) |
|-------------------------|----------------------------------|
| 4.2                     | vLLM: `0.8.3`                    |

### NVIDIA CUDA

| CUDA Version (Variant) | Inference Service (Version List)                                                                           |
|------------------------|------------------------------------------------------------------------------------------------------------|
| 12.8                   | vLLM: `0.11.0`, `0.10.2`, `0.10.1.1`, `0.10.0` <br/> SGLang: `0.5.5`, `0.5.4.post3` <br/> VoxBox: `0.0.20` |
| 12.6                   | vLLM: `0.11.0`, `0.10.2`, `0.10.1.1`, `0.10.0` <br/> VoxBox: `0.0.20`                                      |
| 12.4                   | vLLM: `0.11.0`, `0.10.2`, `0.10.1.1`, `0.10.0` <br/> VoxBox: `0.0.20`                                      |

### Hygon DTK

| DTK Version (Variant) | Inference Service (Version List) |
|-----------------------|----------------------------------|
| 25.04                 | vLLM: `0.9.2`, `0.8.5`           |

### MetaX MACA

| MACA Version (Variant) | Inference Service (Version List) |
|------------------------|----------------------------------|
| 3.2                    | vLLM: `0.10.2`                   |
| 3.0                    | vLLM: `0.9.1`                    |

### AMD ROCm

| ROCm Version (Variant) | Inference Service (Version List) |
|------------------------|----------------------------------|
| 7.0                    | vLLM: `0.11.0`                   |
| 6.4                    | vLLM: `0.10.2`                   |
| 6.3                    | vLLM: `0.10.1.1`, `0.10.0`       |

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
3. Update [pack.yml](.github/workflows/pack.yml) to include the new backend in the build matrix.
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
