from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


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


@lru_cache
def list_runners(
    backend: str | None = None,
    backend_version: str | None = None,
    service: str | None = None,
    service_version: str | None = None,
    platform: str | None = None,
) -> Runners:
    """
    Returns runner list that match the specified criteria.

    :param backend: Optional backend name to filter by.
    :param backend_version: Optional backend version to filter by.
    :param service: Optional service name to filter by.
    :param service_version: Optional service version to filter by.
    :param platform: Optional platform to filter by.
    :return: A list of matching runner.
    """
    data_path = resources.files(__package__).joinpath("runner.json")
    with data_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
        runners = [Runner(**item) for item in data]

    return [
        item
        for item in runners
        if (backend is None or item.backend == backend)
        and (backend_version is None or item.backend_version == backend_version)
        and (service is None or item.service == service)
        and (service_version is None or item.service_version == service_version)
        and (platform is None or item.platform == platform)
    ]
