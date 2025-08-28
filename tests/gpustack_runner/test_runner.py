import pytest
from fixtures import load

from gpustack_runner import list_backend_runners, list_runners, list_service_runners


@pytest.mark.parametrize(
    "name, filters, expected",
    load(
        "test_list_runners_by_backend.json",
    ),
)
def test_list_runners_by_backend(name, filters, expected):
    actual = list_runners(**filters, todict=True)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )


@pytest.mark.parametrize(
    "name, filters, expected",
    load(
        "test_list_backend_runners.json",
    ),
)
def test_list_backend_runners(name, filters, expected):
    actual = list_backend_runners(**filters, todict=True)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )


@pytest.mark.parametrize(
    "name, filters, expected",
    load(
        "test_list_service_runners.json",
    ),
)
def test_list_service_runners(name, filters, expected):
    actual = list_service_runners(**filters, todict=True)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )
