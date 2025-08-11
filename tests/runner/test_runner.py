import pytest
from fixtures import load

from runner import build_backend_runners, list_runners


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
        "test_list_runners_by_backend_version.json",
    ),
)
def test_list_runners_by_backend_version(name, filters, expected):
    actual = list_runners(**filters, todict=True)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )


@pytest.mark.parametrize(
    "name, filters, expected",
    load(
        "test_build_backend_runners.json",
    ),
)
def test_build_backend_runners(name, filters, expected):
    runners = list_runners(**filters)
    actual = build_backend_runners(runners, todict=True)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )


@pytest.mark.parametrize(
    "name, filters, expected",
    load(
        "test_build_service_runners.json",
    ),
)
def test_build_service_runners(name, filters, expected):
    runners = list_runners(**filters)
    actual = build_backend_runners(runners, todict=True)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )
