from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from dataclasses_json import dataclass_json


def _remove_none_from_dict_(d: list[tuple[str, Any]]) -> dict:
    """
    Removes keys with None values from the dictionary.
    """
    return {k: v for k, v in d if v is not None}


@dataclass_json
@dataclass
class Runner:
    backend: str
    """
    The backend name, e.g. "cann", "cuda", "rocm", etc.
    """
    backend_version: str
    """
    The backend version, e.g. "8.2.rc1", "12.4.1", "6.4.2", etc.
    """
    backend_variant: str
    """
    The backend variant, e.g. "910b", etc.
    """
    service: str
    """
    The service name, e.g. "vllm", "voxbox", etc.
    """
    service_version: str
    """
    The service version, e.g. "0.10.0", "0.4.10", etc.
    """
    platform: str
    """
    The platform, e.g. "linux/amd64", "linux/arm64", etc.
    """
    docker_image: str
    """
    The Docker image name.
    """


Runners = list[Runner]
"""
Example of Runners:
[
    {
        "backend": "cann",
        "backend_version": "8.2.rc1",
        "backend_variant": "910b",
        "service": "vllm",
        "service_version": "0.10.0",
        "platform": "linux/amd64",
        "docker_image": "gpustack/runner:cann8.2.rc1-vllm0.10.0"
    }
]
"""


def convert_runners_to_dict(runners: Runners) -> list[dict]:
    """
    Converts a list of Runner objects to a list of dictionaries.

    :param runners: A list of Runner objects.
    :return: A list of dictionaries created from the input Runner objects.
    """
    return [asdict(r, dict_factory=_remove_none_from_dict_) for r in runners]


@lru_cache
def list_runners(**kwargs) -> Runners | list[dict]:
    """
    Returns runner list that match the specified criteria.

    :param kwargs: The criteria to filter runners, possible keys are:
            'backend',
            'backend_version',
            'backend_version_prefix',
            'backend_variant',
            'service',
            'service_version',
            'service_version_prefix',
            'platform'.
            Also accepts **todict** to return a list of dictionaries instead of Runner objects.
    :return: A list of matching runner.
    """
    data_path = resources.files(__package__).joinpath("runner.json")
    with data_path.open("r", encoding="utf-8") as f:
        json_list = json.load(f)
        runners = [Runner(**item) for item in json_list]

    todict = kwargs.pop("todict", False)
    if not kwargs:
        return convert_runners_to_dict(runners) if todict else runners

    allowed_keys = {
        "backend",
        "backend_version",
        "backend_version_prefix",
        "backend_variant",
        "service",
        "service_version",
        "service_version_prefix",
        "platform",
    }
    given_keys = set(kwargs.keys())
    if not given_keys.issubset(allowed_keys):
        errmsg = f"Invalid keys in kwargs: {given_keys - allowed_keys}."
        raise ValueError(errmsg)

    results: Runners = []
    for item in runners:
        match = True
        for key, value in kwargs.items():
            if key.endswith("_prefix"):
                attr_value = getattr(item, key[:-7])
                if not attr_value.startswith(value):
                    match = False
                    break
            elif getattr(item, key) != value:
                match = False
                break
        if match:
            results.append(item)

    return convert_runners_to_dict(results) if todict else results


@dataclass_json
@dataclass
class ServicePlatformedRunner:
    platform: str
    """
    The platform, e.g. "linux/amd64", "linux/arm64", etc.
    """
    docker_image: str
    """
    The Docker image name.
    """


@dataclass_json
@dataclass
class ServiceVersionedRunner:
    version: str
    """
    The service version, e.g. "0.10.0", "0.4.10", etc.
    """
    platforms: list[ServicePlatformedRunner] | None = None
    """
    A list of ServicePlatformedRunner objects, each containing platform and docker_image.
    """
    backends: list[BackendRunner] | None = None
    """
    A list of BackendRunner objects, each containing backend and versions.
    """


@dataclass_json
@dataclass
class ServiceRunner:
    service: str
    """
    The service name, e.g. "vllm", "voxbox", etc.
    """
    versions: list[ServiceVersionedRunner]
    """
    A list of ServiceVersionedRunner objects, each containing version and platforms.
    """


@dataclass_json
@dataclass
class BackendVariantRunner:
    variant: str
    """
    The backend variant, e.g. "910b", etc.
    """
    services: list[ServiceRunner] | None = None
    """
    A list of ServicedRunner objects, each containing service and versions.
    """
    platforms: list[ServicePlatformedRunner] | None = None
    """
    A list of ServicePlatformedRunner objects, each containing platform and docker_image.
    """


@dataclass_json
@dataclass
class BackendVersionedRunner:
    version: str
    """
    The backend version, e.g. "8.2.rc1", "12.4.1", "6.4.2", etc.
    """
    variants: list[BackendVariantRunner]
    """
    A list of BackendVariantRunner objects, each containing variant and services.
    """


@dataclass_json
@dataclass
class BackendRunner:
    backend: str
    """
    The backend name, e.g. "cann", "cuda", "rocm", etc.
    """
    versions: list[BackendVersionedRunner]
    """
    A list of BackendVersionedRunner objects, each containing version and variants.
    """


BackendRunners = list[BackendRunner]
"""
Example of BackendRunners:
[
    {
        "backend": "cann",
        "versions": [
            {
                "version": "8.2.rc1",
                "variants": [
                    {
                        "variant": "910b",
                        "services": [
                            {
                                "service": "vllm",
                                "versions": [
                                    {
                                        "version": "0.10.0",
                                        "platforms": [
                                            {
                                                "platform": "linux/amd64",
                                                "docker_image": "gpustack/runner:cann8.2.rc1-vllm0.10.0"
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
]
"""

ServiceRunners = list[ServiceRunner]
"""
Example of ServiceRunners:
[
    {
        "service": "vllm",
        "versions": [
            {
                "version": "0.10.0",
                "backends": [
                    {
                        "backend": "cann",
                        "versions": [
                            {
                                "version": "8.2.rc1",
                                "variants": [
                                    {
                                        "variant": "910b",
                                        "platforms": [
                                            {
                                                "platform": "linux/amd64",
                                                "docker_image": "gpustack/runner:cann8.2.rc1-vllm0.10.0"
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
]
"""


def convert_backend_runners_to_dict(
    backend_runners: BackendRunners,
) -> list[dict]:
    """
    Converts a list of BackendRunner objects to a list of dictionaries.

    :param backend_runners: A list of BackendRunner objects.
    :return: A list of dictionaries created from the input BackendRunner objects.
    """
    return [asdict(br, dict_factory=_remove_none_from_dict_) for br in backend_runners]


def build_backend_runners(  # noqa: C901
    runners: Runners,
    todict: bool = False,
) -> BackendRunners | list[dict]:
    """
    Builds a structured representation of backend runners from a list of Runner objects.

    :param runners: A list of Runner objects.
    :param todict: If True, returns a list of dictionaries instead of BackendRunner objects.
    :return: A list of BackendRunner objects structured by backend, version, variant, service, and platform.
    """
    results: BackendRunners = []

    for runner in runners:
        # Find or create the backend entry
        backend_entry = next(
            (br for br in results if br.backend == runner.backend),
            None,
        )
        if not backend_entry:
            backend_entry = BackendRunner(
                backend=runner.backend,
                versions=[],
            )
            results.append(backend_entry)

        # Find or create the version entry
        version_entry = next(
            (
                bv
                for bv in backend_entry.versions
                if bv.version == runner.backend_version
            ),
            None,
        )
        if not version_entry:
            version_entry = BackendVersionedRunner(
                version=runner.backend_version,
                variants=[],
            )
            backend_entry.versions.append(version_entry)

        # Find or create the variant entry
        variant_entry = next(
            (
                bv
                for bv in version_entry.variants
                if bv.variant == runner.backend_variant
            ),
            None,
        )
        if not variant_entry:
            variant_entry = BackendVariantRunner(
                variant=runner.backend_variant,
                services=[],
            )
            version_entry.variants.append(variant_entry)

        # Find or create the service entry
        service_entry = next(
            (s for s in variant_entry.services if s.service == runner.service),
            None,
        )
        if not service_entry:
            service_entry = ServiceRunner(
                service=runner.service,
                versions=[],
            )
            variant_entry.services.append(service_entry)

        # Find or create the service version entry
        service_version_entry = next(
            (
                sv
                for sv in service_entry.versions
                if sv.version == runner.service_version
            ),
            None,
        )
        if not service_version_entry:
            service_version_entry = ServiceVersionedRunner(
                version=runner.service_version,
                platforms=[],
            )
            service_entry.versions.append(service_version_entry)

        # Add the platform and docker image
        platformed_runner = ServicePlatformedRunner(
            platform=runner.platform,
            docker_image=runner.docker_image,
        )
        service_version_entry.platforms.append(platformed_runner)

    # Sort the results for consistent ordering
    results.sort(key=lambda br: br.backend)
    for backend in results:
        backend.versions.sort(key=lambda bv: bv.version)
        for version in backend.versions:
            version.variants.sort(key=lambda bv: bv.variant)
            for variant in version.variants:
                variant.services.sort(key=lambda s: s.service)
                for service in variant.services:
                    service.versions.sort(key=lambda sv: sv.version)
                    for service_version in service.versions:
                        service_version.platforms.sort(key=lambda p: p.platform)

    return convert_backend_runners_to_dict(results) if todict else results


def convert_service_runners_to_dict(
    service_runners: ServiceRunners,
) -> list[dict]:
    """
    Converts a list of ServiceRunner objects to a list of dictionaries.

    :param service_runners: A list of ServiceRunner objects.
    :return: A list of dictionaries created from the input ServiceRunner objects.
    """
    return [asdict(sr, dict_factory=_remove_none_from_dict_) for sr in service_runners]


def build_service_runners(  # noqa: C901
    runners: Runners,
    todict: bool = False,
) -> list[ServiceRunner] | list[dict]:
    """
    Builds a structured representation of service runners from a list of Runner objects.

    :param runners: A list of Runner objects.
    :param todict: If True, returns a list of dictionaries instead of ServiceRunner objects.
    :return: A list of ServiceRunner objects structured by service, version, backend, and platform.
    """
    results: ServiceRunners = []

    for runner in runners:
        # Find or create the service entry
        service_entry = next(
            (s for s in results if s.service == runner.service),
            None,
        )
        if not service_entry:
            service_entry = ServiceRunner(
                service=runner.service,
                versions=[],
            )
            results.append(service_entry)

        # Find or create the service version entry
        service_version_entry = next(
            (
                sv
                for sv in service_entry.versions
                if sv.version == runner.service_version
            ),
            None,
        )
        if not service_version_entry:
            service_version_entry = ServiceVersionedRunner(
                version=runner.service_version,
                backends=[],
            )
            service_entry.versions.append(service_version_entry)

        # Find or create the backend entry
        backend_entry = next(
            (b for b in service_version_entry.backends if b.backend == runner.backend),
            None,
        )
        if not backend_entry:
            backend_entry = BackendRunner(
                backend=runner.backend,
                versions=[],
            )
            service_version_entry.backends.append(backend_entry)

        # Find or create the backend version entry
        backend_version_entry = next(
            (
                bv
                for bv in backend_entry.versions
                if bv.version == runner.backend_version
            ),
            None,
        )
        if not backend_version_entry:
            backend_version_entry = BackendVersionedRunner(
                version=runner.backend_version,
                variants=[],
            )
            backend_entry.versions.append(backend_version_entry)

        # Find or create the variant entry
        variant_entry = next(
            (
                bv
                for bv in backend_version_entry.variants
                if bv.variant == runner.backend_variant
            ),
            None,
        )
        if not variant_entry:
            variant_entry = BackendVariantRunner(
                variant=runner.backend_variant,
                platforms=[],
            )
            backend_version_entry.variants.append(variant_entry)

        # Add the platform and docker image
        platformed_runner = ServicePlatformedRunner(
            platform=runner.platform,
            docker_image=runner.docker_image,
        )
        variant_entry.platforms.append(platformed_runner)

    # Sort the results for consistent ordering
    results.sort(key=lambda sr: sr.service)
    for service in results:
        service.versions.sort(key=lambda sv: sv.version)
        for service_version in service.versions:
            service_version.backends.sort(key=lambda b: b.backend)
            for backend in service_version.backends:
                backend.versions.sort(key=lambda bv: bv.version)
                for backend_version in backend.versions:
                    backend_version.variants.sort(key=lambda bv: bv.variant)
                    for variant in backend_version.variants:
                        variant.platforms.sort(key=lambda p: p.platform)

    return convert_service_runners_to_dict(results) if todict else results
