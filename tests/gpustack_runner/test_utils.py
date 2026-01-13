import pytest
from fixtures import load

from gpustack_runner.__utils__ import (
    merge_image,
    replace_image_with,
    split_image,
)


@pytest.mark.parametrize(
    "name, kwargs, expected",
    load(
        "test_split_image.json",
    ),
)
def test_split_image(name, kwargs, expected):
    actual = split_image(**kwargs)
    assert actual == tuple(expected), (
        f"case {name} expected {expected}, but got {actual} for kwargs: {kwargs}"
    )


@pytest.mark.parametrize(
    "name, kwargs, expected",
    load(
        "test_merge_image.json",
    ),
)
def test_merge_image(name, kwargs, expected):
    actual = merge_image(**kwargs)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for kwargs: {kwargs}"
    )


@pytest.mark.parametrize(
    "name, kwargs, expected",
    load(
        "test_replace_image_with.json",
    ),
)
def test_replace_image_with(name, kwargs, expected):
    actual = replace_image_with(**kwargs)
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for kwargs: {kwargs}"
    )
