# GPUStack Runner

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
