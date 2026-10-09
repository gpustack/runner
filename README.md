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

See [Supported runners](docs/supported-runners.md) for backends, inference services, and supported versions.

CANN/vLLM images use stable vLLM releases. An `(rc)` label identifies a prerelease vLLM-Ascend plugin.

## Documentation

- [Packaging](docs/packaging.md): service Dockerfiles, matrix selection, image builds, and final-image collection.
- [Dependency metadata](docs/dependency-metadata.md): installed package records and queries.
- [Release automation](docs/release-automation.md): weekly proposals, model configuration, PR commands, and post-merge Pack.
- [Project instructions](AGENTS.md): source navigation, development checks, and contribution conventions.

Certify contributions under [DCO](DCO) with `git commit -s`.
Companies and projects can add their usage to [ADOPTERS.md](ADOPTERS.md).

## License

Copyright (c) 2026 The GPUStack authors.
Licensed under [Apache License 2.0](LICENSE).
