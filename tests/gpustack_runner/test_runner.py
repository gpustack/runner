import pytest
from fixtures import load

from gpustack_runner import (
    DockerImage,
    list_backend_runners,
    list_runners,
    list_service_runners,
)
from gpustack_runner.runner import version_sort_key


@pytest.mark.parametrize(
    "name, versions, expected",
    [
        # Pure numeric versions must sort by value, not lexicographically,
        # so double-digit patch/minor segments outrank single-digit ones.
        (
            "numeric patch double digit",
            ["0.5.2", "0.5.10", "0.5.9", "0.5.12", "0.5.14"],
            ["0.5.14", "0.5.12", "0.5.10", "0.5.9", "0.5.2"],
        ),
        (
            "numeric minor rolls over ten",
            ["0.9.0", "0.10.0", "0.2.0", "1.0.0"],
            ["1.0.0", "0.10.0", "0.9.0", "0.2.0"],
        ),
        (
            "four segment versions",
            ["0.10.0", "0.10.1.1", "0.10.2", "0.9.2"],
            ["0.10.2", "0.10.1.1", "0.10.0", "0.9.2"],
        ),
        # Regression for gpustack/gpustack#5792: a segment gluing digits and
        # letters together (``10rc0``) must not raise TypeError when compared
        # against pure-numeric segments (``14``) at the same position.
        (
            "glued prerelease among numeric (issue 5792)",
            [
                "0.5.2",
                "0.5.6",
                "0.5.7",
                "0.5.9",
                "0.5.10",
                "0.5.10rc0",
                "0.5.12",
                "0.5.14",
                "0.5.4.post3",
                "0.5.5.post3",
                "0.5.6.post2",
                "0.5.8.post1",
                "0.5.12.post1",
                "0.5.1.post3",
            ],
            [
                "0.5.14",
                "0.5.12.post1",
                "0.5.12",
                "0.5.10",
                "0.5.10rc0",
                "0.5.9",
                "0.5.8.post1",
                "0.5.7",
                "0.5.6.post2",
                "0.5.6",
                "0.5.5.post3",
                "0.5.4.post3",
                "0.5.2",
                "0.5.1.post3",
            ],
        ),
        # A pre-release must sort *before* its final release, and post-releases
        # *after* it (PEP 440 ordering).
        (
            "prerelease ranks below final release",
            ["0.5.10", "0.5.10rc0", "0.5.10rc1"],
            ["0.5.10", "0.5.10rc1", "0.5.10rc0"],
        ),
        (
            "post release ranks above final release",
            ["1.0.0", "1.0.0.post1", "1.0.0.post2"],
            ["1.0.0.post2", "1.0.0.post1", "1.0.0"],
        ),
        # mindie-style ``X.Y.rcN`` (rc split onto its own segment) also parses.
        (
            "mindie rc versions",
            ["2.1.rc1", "2.1.rc2", "2.2.rc1", "2.3.0"],
            ["2.3.0", "2.2.rc1", "2.1.rc2", "2.1.rc1"],
        ),
        # Non-PEP440 tags never raise and rank below every real version.
        (
            "unparseable tags only",
            ["latest", "main", "stable"],
            ["stable", "main", "latest"],
        ),
        (
            "real versions outrank tags",
            ["1.0.0", "latest", "0.9.0"],
            ["1.0.0", "0.9.0", "latest"],
        ),
        (
            "single segment",
            ["7"],
            ["7"],
        ),
    ],
)
def test_version_sort_key(name, versions, expected):
    actual = sorted(versions, key=version_sort_key, reverse=True)
    assert actual == expected, f"case {name} expected {expected}, but got {actual}"


def test_build_runners_sort_bundled_catalog_without_error():
    """
    Building runners over the bundled catalog must not raise, guarding against
    gpustack/gpustack#5792 where a real catalog entry (``sglang 0.5.10rc0``)
    made the internal version sort throw
    ``TypeError: '<' not supported between instances of 'str' and 'int'``.

    ``list_backend_runners`` and ``list_service_runners`` perform every version
    sort the build functions rely on, so a clean call exercises them all.
    """
    # Both entrypoints are ``@lru_cache``d; clear them so the version-sorting
    # code paths actually run instead of returning a cached result from an
    # earlier test in the session.
    list_backend_runners.cache_clear()
    list_service_runners.cache_clear()
    backend_runners = list_backend_runners(todict=True)
    service_runners = list_service_runners(todict=True)
    assert backend_runners, "expected a non-empty backend runner catalog"
    assert service_runners, "expected a non-empty service runner catalog"


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
