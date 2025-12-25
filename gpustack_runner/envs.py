from __future__ import annotations

from functools import lru_cache
from os import getenv as sys_getenv
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    # Global

    GPUSTACK_RUNNER_DEFAULT_NAMESPACE: str | None = None
    """
    Namespace for default runner images.
    If not set, it should be "gpustack".
    """

# --8<-- [start:env-vars-definition]

variables: dict[str, Callable[[], Any]] = {
    # Global
    "GPUSTACK_RUNNER_DEFAULT_NAMESPACE": lambda: trim_str(
        getenvs(
            keys=[
                "GPUSTACK_RUNNER_DEFAULT_NAMESPACE",
                "GPUSTACK_RUNTIME_DEPLOY_DEFAULT_NAMESPACE",  ## Compatible with gpustack/gpustack_runtime.
            ],
        ),
    ),
}


# --8<-- [end:env-vars-definition]


@lru_cache
def __getattr__(name: str):
    # lazy evaluation of environment variables
    if name in variables:
        return variables[name]()
    msg = f"module {__name__} has no attribute {name}"
    raise AttributeError(msg)


def __dir__():
    return list(variables.keys())


def trim_str(value: str | None) -> str | None:
    """
    Trim leading and trailing whitespace from a string.

    Args:
        value:
            The string to trim.

    Returns:
        The trimmed string, or None if the input is None.

    """
    if value is not None:
        return value.strip()
    return None


_ENV_PREFIX = "GPUSTACK_RUNNER_"


def getenv(key: str, default=None) -> any | None:
    """
    Get the value of an environment variable.
    Try headless module variable if the key starts with "GPUSTACK_RUNNER_".

    Args:
        key:
            The environment variable key.
        default:
            The default value if the key is not found.

    Returns:
        The value of the environment variable if it exists, otherwise None.

    """
    value = sys_getenv(key)
    if value is not None:
        return value
    if key.startswith(_ENV_PREFIX):
        headless_key = key.removeprefix(_ENV_PREFIX)
        return sys_getenv(headless_key, default)
    return default


def getenvs(keys: list[str], default=None) -> any | None:
    """
    Get the value of an environment variable.
    Return the first found value among the provided keys.

    Args:
        keys:
            The environment variable key(s).
        default:
            The default value if none of the keys are found.

    Returns:
        The value of the environment variable if it exists, otherwise None.

    """
    for key in keys:
        value = getenv(key)
        if value is not None:
            return value
    return default
