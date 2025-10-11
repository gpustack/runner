import pytest
from fixtures import load

from gpustack_runner import (
    DockerImage,
    list_backend_runners,
    list_runners,
    list_service_runners,
)


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
        "test_list_runners_by_prefix.json",
    ),
)
def test_list_runners_by_prefix(name, filters, expected):
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


@pytest.mark.parametrize(
    "name, image, expected",
    load(
        "test_docker_image.json",
    ),
)
def test_docker_image(name, image, expected):
    actual = DockerImage.from_string(image)
    assert actual is not None, f"case {name} failed to parse image: {image}"
    assert actual.to_dict() == expected, (
        f"case {name} expected {expected}, but got {actual.to_dict()} for image: {image}"
    )
    assert str(actual) == image, (
        f"case {name} expected {image}, but got {actual!s} for image: {image}"
    )
