# GPUStack Runner

[![License](https://img.shields.io/github/license/gpustack/runner?logo=apache&label=License)](./LICENSE)
[![PyPI](https://img.shields.io/pypi/v/gpustack-runner?logo=pypi&label=PyPI)](https://pypi.org/project/gpustack-runner/)
[![Latest Release](https://img.shields.io/github/v/release/gpustack/runner?logo=semanticrelease&label=Release&include_prereleases)](https://github.com/gpustack/runner/releases/latest)
[![Docker Pulls](https://img.shields.io/docker/pulls/gpustack/runner?logo=docker&logoColor=fff&label=Docker%20Pulls)](https://hub.docker.com/r/gpustack/runner)
[![Ask DeepWiki](https://img.shields.io/badge/Ask_DeepWiki-purple?logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAACXBIWXMAAAPoAAAD6AG1e1JrAAACIUlEQVRYw+2XP2gUQRTGv7d3JhYWQawkIBaCVWzETos0gmAnVoKNTSoLK0E7EQQrC20sBVFBtLPQRgTBtBaKjYgIQUSxiJq7fT+LvCGPJZdNLt4dQj5Y3u7sznzfzLw/s9IO/icANiniCujEfWdsQgBLxAbsbraPZcmBfcAt4DNwKQsZNfEUsAB8YRV12LfA6ZHuedg7AO7ed/c+UBcbQhbiu+6wXIM6EnZWkszMJe2Ke0n6I2la0v51hFeSMLN6OwIK6jJwEBdUYb2MAxRSz6sY4geiahFgLe1Hwq6YWe3us8AN4FQQU4QM64SPY69Xyr43fADgNjAPXHb3peSsD4FDQ0VLEjAHvIhBPS6AHvA1bBO9JPAXcHFbIRtJ5yzwIQZ9CZwAusDJENIkLqsG8DpNyIZJwSUk9wLHgakcesC1JCCjiHm1kYDNOEjptCxpSVK/8f73OFLxPLAYM3oCzEX7MXf/lJbc/8kWpA4HgQdpYI9IWAbeh83whi84cHXL+58EPBoQhnmm94EzwE3gZ2p/Dhzdbhg+TaRr01x7ftb4/jBwFzjXrCvDpmLW9crVLNeR9CaapoGemb2TdCERW1tNaBNQ8jktwmozqwtpqRNtdWAjARYk39IS12ZWRX7vmJmA71nQZgi36gN7gCvAj5xc3P0jcH7kx7Ik5IC73wsh14GZsZySow5002l4Jr0b6+m4eSyvpAn8lEzsx2QHo8RfUrlN+uPq4ksAAAAASUVORK5CYII=)](https://deepwiki.com/gpustack/runner)

GPUStack Runner registers accelerated backends and inference services for GPUStack.
This repository maintains the Python library, container recipes, and measured runner catalog.

## Quick usage

Install the library:

```sh
pip install gpustack-runner
```

Select runners with the Python API:

```python
from gpustack_runner import list_runners

runners = list_runners(
    backend="cuda",
    service="vllm",
    dependencies=(("lmcache", ">=0.4.6"),),
    with_unknown_dependencies=False,
)
```

See the [API reference](docs/modules/gpustack_runner.md) for selection options.
The [dependency guide](docs/dependency-metadata.md) explains unknown collection, absent packages, and raw installed versions.

## Supported runners

Each cell shows the newest supported engine version with its runtime line, and every supported version is listed in [Supported runners](docs/supported-runners.md).

| Backend | vLLM | SGLang | MindIE | VoxBox |
| --- | --- | --- | --- | --- |
| [Ascend CANN](docs/supported-runners.md#ascend-cann) | `0.23.0` (9.1) | `0.5.12.post1` (8.5) | `2.3.0` (8.5) | |
| [Iluvatar CoreX](docs/supported-runners.md#iluvatar-corex) | `0.8.3` (4.2) | | | |
| [NVIDIA CUDA](docs/supported-runners.md#nvidia-cuda) | `0.29.0` (13.0) | `0.5.18` (13.0) | | `0.0.21` (12.8) |
| [Hygon DTK](docs/supported-runners.md#hygon-dtk) | `0.18.1` (26.04) | `0.5.10` (26.04) | | |
| [T-Head HGGC](docs/supported-runners.md#t-head-hggc) | `0.23.0` (13.0) | `0.5.12` (13.0) | | |
| [MetaX MACA](docs/supported-runners.md#metax-maca) | `0.21.0` (3.7) | `0.5.11` (3.7) | | |
| [MThreads MUSA](docs/supported-runners.md#mthreads-musa) | `0.9.2` (4.1.0) | `0.5.7` (4.3.2) | | |
| [AMD ROCm](docs/supported-runners.md#amd-rocm) | `0.29.0` (7.2) | `0.5.18` (7.2) | | |

CANN/vLLM images use stable vLLM releases. An `(rc)` label identifies a prerelease vLLM-Ascend plugin.

## Documentation

- [Packaging](docs/packaging.md): service Dockerfiles, matrix selection, image builds, and final-image collection.
- [Dependency metadata](docs/dependency-metadata.md): installed package records and queries.
- [Release automation](docs/release-automation.md): weekly proposals, model configuration, PR commands, and post-merge Pack.
- [Project instructions](AGENTS.md): source navigation, development checks, and contribution conventions.

## Contributing

Contributions are welcome. Commits must carry a `Signed-off-by` line certifying the
[Developer Certificate of Origin](./DCO).

Using GPUStack Runner in production? Add your company or project to [ADOPTERS.md](./ADOPTERS.md)
via pull request.

## License

Copyright (c) 2026 The GPUStack authors.
Licensed under [Apache License 2.0](LICENSE).
