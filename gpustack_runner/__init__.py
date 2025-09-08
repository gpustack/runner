from __future__ import annotations

from enum import Enum

from ._version import commit_id, version, version_tuple
from .runner import (
    BackendRunners,
    Runners,
    ServiceRunners,
    list_backend_runners,
    list_runners,
    list_service_runners,
)


class ManufacturerEnum(str, Enum):
    """
    Enum for Manufacturers.
    """

    UNKNOWN = "unknown"
    """
    Unknown Manufacturer
    """
    NVIDIA = "nvidia"
    """
    NVIDIA Corporation
    """
    AMD = "amd"
    """
    Advanced Micro Devices, Inc.
    """
    ASCEND = "ascend"
    """
    Huawei Ascend
    """
    HYGON = "hygon"
    """
    Hygon Information Technology Co., Ltd.
    """
    ILUVATAR = "iluvatar"
    """
    Iluvatar CoreX
    """


_MANUFACTURER_BACKEND_MAPPING: dict[ManufacturerEnum, str] = {
    ManufacturerEnum.NVIDIA: "cuda",
    ManufacturerEnum.AMD: "rocm",
    ManufacturerEnum.ASCEND: "cann",
    ManufacturerEnum.HYGON: "dtk",
    ManufacturerEnum.ILUVATAR: "corex",
}
"""
Mapping of manufacturer to runtime backend.
"""

_BACKEND_VISIBLE_DEVICES_ENV_MAPPING: dict[str, list[str]] = {
    "cuda": ["CUDA_VISIBLE_DEVICES"],
    "rocm": ["ROCR_VISIBLE_DEVICES"],
    "cann": ["ASCEND_RT_VISIBLE_DEVICES", "NPU_VISIBLE_DEVICES"],
    "dtk": ["HIP_VISIBLE_DEVICES"],
    "corex": ["CUDA_VISIBLE_DEVICES"],
}
"""
Mapping of envs to tell the related backend toolkit which devices are visible inside a container.
"""

_CONTAINER_BACKEND_VISIBLE_DEVICES_ENV_MAPPING: dict[str, str] = {
    "cuda": "NVIDIA_VISIBLE_DEVICES",
    "rocm": "AMD_VISIBLE_DEVICES",
    "cann": "ASCEND_VISIBLE_DEVICES",
    "dtk": "HYGON_VISIBLE_DEVICES",  ## TODO(thxCode): confirm with HYGON
    "corex": "ILUVATAR_VISIBLE_DEVICES",  ## TODO(thxCode): confirm with ILUVATAR
}
"""
Mapping of envs for container runtime to set visible devices for a container.
"""


def manufacturer_to_backend(manufacturer: ManufacturerEnum) -> str | None:
    """
    Convert manufacturer to runtime backend,
    e.g., NVIDIA -> cuda, AMD -> rocm.

    This is used to determine the appropriate runtime backend
    based on the device manufacturer.

    Args:
        manufacturer: The manufacturer of the device.

    Returns:
        The corresponding runtime backend. None if the manufacturer is unknown.

    """
    return _MANUFACTURER_BACKEND_MAPPING.get(manufacturer)


def backend_to_manufacturer(backend: str) -> ManufacturerEnum:
    """
    Convert runtime backend to manufacturer,
    e.g., cuda -> NVIDIA, rocm -> AMD.

    This is used to determine the appropriate manufacturer
    based on the runtime backend.

    Args:
        backend: The runtime backend.

    Returns:
        The corresponding manufacturer. UNKNOWN if the backend is unknown.

    """
    for manu, back in _MANUFACTURER_BACKEND_MAPPING.items():
        if back == backend:
            return manu

    return ManufacturerEnum.UNKNOWN


def backend_visible_devices_env(backend: str) -> list[str]:
    """
    Get the mapping of backend to its corresponding *_VISIBLE_DEVICES env list.

    It is used to tell the related backend toolkit which devices are visible inside a container.

    Args:
        backend: The runtime backend (e.g., 'cuda', 'rocm').

    Returns:
        The environment variable name used to specify visible devices of toolkit.

    """
    return _BACKEND_VISIBLE_DEVICES_ENV_MAPPING.get(backend, [])


def container_backend_visible_devices_env(backend: str) -> str | None:
    """
    Get the mapping of container's backend to its corresponding *_VISIBLE_DEVICES env.

    Doesn't like `backend_visible_devices_env`,
    it returns the env which is used to inject host devices into container only.

    Args:
        backend: The runtime backend (e.g., 'cuda', 'rocm').

    Returns:
        The environment variable name used by container runtimes
        to specify visible devices (used to inject host devices into container) for the given backend.

    """
    return _CONTAINER_BACKEND_VISIBLE_DEVICES_ENV_MAPPING.get(backend)


__all__ = [
    "BackendRunners",
    "ManufacturerEnum",
    "Runners",
    "ServiceRunners",
    "backend_to_manufacturer",
    "backend_visible_devices_env",
    "commit_id",
    "container_backend_visible_devices_env",
    "list_backend_runners",
    "list_runners",
    "list_service_runners",
    "manufacturer_to_backend",
    "version",
    "version_tuple",
]
