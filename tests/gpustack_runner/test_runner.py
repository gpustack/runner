from pathlib import Path

import pytest
from fixtures import load

from gpustack_runner import (
    DockerImage,
    list_backend_runners,
    list_runners,
    list_service_runners,
)
from gpustack_runner.runner import (
    Runner,
    _match_dependencies,
    _resolve_dependency_conditions,
    version_sort_key,
)

DEPENDENCIES_CATALOG = str(
    Path(__file__).parent / "fixtures" / "test_list_runners_by_dependencies.json",
)
"""
A synthetic runner catalog whose entries carry ``dependencies``, used to drive
the dependency filtering through the real query entrypoints. The bundled
catalog cannot serve that purpose: which of its entries carry probe data is
maintained by the image-build workflow and changes over time, so deterministic
matching cases need a fixed catalog.
"""


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


def _matches(
    dependencies,
    conditions,
    with_unknown_dependencies=True,
) -> bool:
    """
    Resolve dependency conditions and match them against a probed dependency map.

    :param dependencies: The probed dependency map of a single runner entry.
    :param conditions: A tuple of ``(dependency name, PEP 440 specifier)`` pairs.
    :param with_unknown_dependencies: Whether unprobed entries are kept.
    :return: True if the entry satisfies every condition.
    """
    return _match_dependencies(
        dependencies,
        _resolve_dependency_conditions(conditions),
        with_unknown_dependencies,
    )


@pytest.mark.parametrize(
    "name, dependencies, conditions, with_unknown_dependencies, expected",
    [
        # No condition at all never filters anything out, whatever the state of
        # the dependency map is.
        ("no condition, probed", {"lmcache": "0.4.3"}, (), True, True),
        ("no condition, unprobed", None, (), True, True),
        ("no condition, unprobed strict", None, (), False, True),
        # Plain ranges.
        (
            "lower bound hit",
            {"lmcache": "0.5.4"},
            (("lmcache", ">=0.4.6"),),
            True,
            True,
        ),
        (
            "lower bound miss",
            {"lmcache": "0.4.3"},
            (("lmcache", ">=0.4.6"),),
            True,
            False,
        ),
        (
            "interval hit",
            {"lmcache": "0.5.4"},
            (("lmcache", ">=0.4.6,<0.6"),),
            True,
            True,
        ),
        (
            "interval miss above",
            {"lmcache": "0.6.0"},
            (("lmcache", ">=0.4.6,<0.6"),),
            True,
            False,
        ),
        (
            "interval miss below",
            {"lmcache": "0.4.3"},
            (("lmcache", ">=0.4.6,<0.6"),),
            True,
            False,
        ),
        ("exact hit", {"lmcache": "0.5.4"}, (("lmcache", "==0.5.4"),), True, True),
        ("exact miss", {"lmcache": "0.5.5"}, (("lmcache", "==0.5.4"),), True, False),
        # Pre-release regression locks: ``SpecifierSet`` excludes pre-releases by
        # default, and dropping ``prereleases=True`` would filter out every rc
        # image, which are the norm here.
        (
            "prerelease matches lower bound (vllm-ascend)",
            {"vllm-ascend": "0.20.2rc1"},
            (("vllm-ascend", ">=0.20.0"),),
            True,
            True,
        ),
        (
            "prerelease matches lower bound (sglang-kernel)",
            {"sglang-kernel": "0.4.6rc0"},
            (("sglang-kernel", ">=0.4.5"),),
            True,
            True,
        ),
        (
            "prerelease of the bound itself stays below it",
            # ``0.4.6rc1 < 0.4.6`` is correct PEP 440 ordering, not a defect.
            # Locked so it is never "fixed" into a match.
            {"lmcache": "0.4.6rc1"},
            (("lmcache", ">=0.4.6"),),
            True,
            False,
        ),
        (
            "empty specifier is a pure existence check",
            # An empty specifier degrades to "installed at all", which is how a
            # commit-pinned dev version stays matchable.
            {"lmcache": "0.3.0.dev0+gaff7d64"},
            (("lmcache", ""),),
            True,
            True,
        ),
        # ``vllm-omni`` is installed from a commit, so its version (real output
        # from ``gpustack/runner:cuda13.0-vllm0.27.1``) carries no information
        # and sorts below its own rc2 under PEP 440. An empty specifier is how
        # to ask about it without making a meaningless comparison.
        (
            "empty specifier hits a commit-pinned dev version (vllm-omni)",
            {"vllm-omni": "0.27.0rc2.dev25+gd77a35a32"},
            (("vllm-omni", ""),),
            True,
            True,
        ),
        (
            "empty specifier still misses when not installed",
            # "No constraint" never degrades to "always true": absence is still
            # absence.
            {},
            (("vllm-omni", ""),),
            True,
            False,
        ),
        # A recorded version that is not PEP 440 must never crash the query.
        # ``SpecifierSet.contains`` raises ``InvalidVersion`` on one, and the
        # same class of input already took down the catalog once
        # (gpustack/gpustack#5792), so both paths are locked here.
        (
            "unparseable version misses a range instead of raising",
            {"torch": "latest"},
            (("torch", ">=2.9"),),
            True,
            False,
        ),
        (
            "unparseable version still satisfies an existence check",
            # The package *is* installed, which is the whole question an empty
            # specifier asks; an unreadable version must not turn it into a miss.
            {"torch": "latest"},
            (("torch", ""),),
            True,
            True,
        ),
        # Unknown names match nothing rather than raising: the whitelist is a
        # build-side file and is not shipped with the library, so a name is just
        # a key lookup into the probed map.
        (
            "unknown name misses instead of raising",
            {"lmcache": "0.5.4"},
            (("lmcahce", ">=0.4.6"),),
            True,
            False,
        ),
        (
            "unknown name misses even unconstrained",
            {"lmcache": "0.5.4"},
            (("lmcahce", ""),),
            True,
            False,
        ),
        # Multiple conditions are ANDed.
        (
            "multiple conditions all hit",
            {"torch": "2.9.0", "transformers": "4.58.2"},
            (("torch", ">=2.9"), ("transformers", ">=4.58")),
            True,
            True,
        ),
        (
            "multiple conditions one misses",
            {"torch": "2.8.0", "transformers": "4.58.2"},
            (("torch", ">=2.9"), ("transformers", ">=4.58")),
            True,
            False,
        ),
        # Unprobed entries (the whole field absent) are kept by default and
        # dropped in strict mode.
        ("unprobed is lenient by default", None, (("lmcache", ">=0.4.6"),), True, True),
        (
            "unprobed is dropped when strict",
            None,
            (("lmcache", ">=0.4.6"),),
            False,
            False,
        ),
        # A probed entry missing the key means "not installed", a different
        # state from "unprobed" that must not get the lenient default.
        (
            "probed but package absent",
            {"torch": "2.8.0"},
            (("lmcache", ">=0.4.6"),),
            True,
            False,
        ),
        (
            "probed with an empty map",
            # ``{}`` is "probed, nothing whitelisted installed"; it must not be
            # confused with the unprobed ``None``.
            {},
            (("lmcache", ">=0.4.6"),),
            True,
            False,
        ),
    ],
)
def test_match_dependencies(
    name,
    dependencies,
    conditions,
    with_unknown_dependencies,
    expected,
):
    actual = _matches(dependencies, conditions, with_unknown_dependencies)
    assert actual is expected, (
        f"case {name} expected {expected}, but got {actual} "
        f"for dependencies: {dependencies} and conditions: {conditions}"
    )


def test_match_dependencies_invalid_specifier():
    with pytest.raises(ValueError, match=r"lmcache.*>=abc|>=abc.*lmcache") as excinfo:
        _matches({"lmcache": "0.5.4"}, (("lmcache", ">=abc"),))
    message = str(excinfo.value)
    assert "lmcache" in message, f"expected the package name in {message!r}"
    assert ">=abc" in message, f"expected the specifier in {message!r}"


def test_match_dependencies_invalid_specifier_of_an_unknown_name():
    """
    The name is no longer validated, but the specifier still is: a malformed
    specifier is a caller input error whatever the name.
    """
    with pytest.raises(ValueError, match=r"lmcahce.*>>>1\.0|>>>1\.0.*lmcahce"):
        _matches({"lmcache": "0.5.4"}, (("lmcahce", ">>>1.0"),))


def test_match_dependencies_invalid_specifier_without_any_entry():
    """
    An invalid specifier is a caller error, so it must be reported even when no
    entry would ever be evaluated against it.
    """
    with pytest.raises(ValueError, match="lmcache"):
        _resolve_dependency_conditions((("lmcache", ">=abc"),))


def test_match_dependencies_malformed_condition_too_short():
    # A natural typo for a single-element condition. It must raise a useful
    # ValueError, not leak "not enough values to unpack" from destructuring.
    with pytest.raises(ValueError, match="lmcache") as excinfo:
        _resolve_dependency_conditions((("lmcache",),))
    message = str(excinfo.value)
    assert "pair" in message, f"expected a hint about the expected shape in {message!r}"


def test_match_dependencies_malformed_condition_too_long():
    with pytest.raises(ValueError, match="lmcache"):
        _resolve_dependency_conditions((("lmcache", ">=0.4.6", "extra"),))


def test_match_dependencies_none_specifier_is_unconstrained():
    # ``None`` is how every other ``list_runners`` filter spells "no
    # constraint", rather than a ``TypeError`` out of ``SpecifierSet``.
    assert _matches({"lmcache": "0.4.3"}, (("lmcache", None),)) is True
    # Unconstrained still requires the package to be installed at all.
    assert _matches({"torch": "2.9.0"}, (("lmcache", None),)) is False


def test_match_dependencies_does_not_validate_names():
    """
    A name the catalog never carries is a miss, not an error.

    The whitelist lives in ``pack/`` and is not shipped with the library, so
    there is nothing to validate a name against. Callers own their spelling.
    """
    assert _matches({"flashinfer-python": "0.2.0"}, (("flashinfer", ">=0.2"),)) is False
    assert _matches({"flashinfer-python": "0.2.0"}, (("flashinfer-python", ">=0.2"),))


@pytest.mark.parametrize(
    "name, filters, expected",
    [
        (
            "no dependency condition returns everything",
            {},
            [
                "gpustack/runner:cann9.1-a3-vllm0.23.0",
                "gpustack/runner:cuda13.0-vllm0.29.0",
                "gpustack/runner:cuda13.0-sglang0.5.10",
                "gpustack/runner:rocm7.0-vllm0.29.0",
                "gpustack/runner:musa4.1-vllm0.9.2",
                "gpustack/runner:corex4.3-vllm0.11.0",
            ],
        ),
        (
            "lmcache lower bound keeps unprobed entries",
            {"dependencies": (("lmcache", ">=0.4.6"),)},
            [
                "gpustack/runner:cann9.1-a3-vllm0.23.0",
                "gpustack/runner:cuda13.0-vllm0.29.0",
                # Unprobed, kept by the lenient default.
                "gpustack/runner:musa4.1-vllm0.9.2",
            ],
        ),
        (
            "lmcache lower bound in strict mode",
            {
                "dependencies": (("lmcache", ">=0.4.6"),),
                "with_unknown_dependencies": False,
            },
            [
                "gpustack/runner:cann9.1-a3-vllm0.23.0",
                "gpustack/runner:cuda13.0-vllm0.29.0",
            ],
        ),
        (
            "upper bound excludes the newer entries",
            {"dependencies": (("lmcache", "<0.5"),)},
            [
                # ``lmcache 0.4.6rc1`` matches with prereleases enabled.
                "gpustack/runner:cuda13.0-sglang0.5.10",
                "gpustack/runner:musa4.1-vllm0.9.2",
            ],
        ),
        (
            "prerelease matches the lower bound",
            {"dependencies": (("sglang-kernel", ">=0.4.5"),)},
            [
                "gpustack/runner:cuda13.0-sglang0.5.10",
                "gpustack/runner:musa4.1-vllm0.9.2",
            ],
        ),
        (
            "multiple conditions are ANDed",
            {
                "dependencies": (("torch", ">=2.9"), ("transformers", ">=4.58")),
            },
            [
                "gpustack/runner:cuda13.0-vllm0.29.0",
                "gpustack/runner:musa4.1-vllm0.9.2",
            ],
        ),
        (
            "dependency conditions combine with the existing criteria",
            {
                "backend": "cuda",
                "dependencies": (("lmcache", ">=0.4.6"),),
            },
            [
                "gpustack/runner:cuda13.0-vllm0.29.0",
            ],
        ),
        (
            "nothing matches",
            {
                "dependencies": (("lmcache", ">=99.0"),),
                "with_unknown_dependencies": False,
            },
            [],
        ),
    ],
)
def test_list_runners_by_dependencies(name, filters, expected):
    actual = [
        r.docker_image for r in list_runners(**filters, data_path=DEPENDENCIES_CATALOG)
    ]
    assert actual == expected, (
        f"case {name} expected {expected}, but got {actual} for filters: {filters}"
    )


def test_list_backend_runners_by_dependencies():
    """
    The dependency criteria must reach ``list_runners`` through the backend
    entrypoint as well.
    """
    actual = list_backend_runners(
        dependencies=(("lmcache", ">=0.4.6"),),
        data_path=DEPENDENCIES_CATALOG,
    )
    assert [br.backend for br in actual] == ["cann", "cuda", "musa"]

    strict = list_backend_runners(
        dependencies=(("lmcache", ">=99.0"),),
        with_unknown_dependencies=False,
        data_path=DEPENDENCIES_CATALOG,
    )
    assert strict == []


def test_list_service_runners_by_dependencies():
    """
    The dependency criteria must reach ``list_runners`` through the service
    entrypoint as well.
    """
    actual = list_service_runners(
        dependencies=(("lmcache", ">=0.4.6"),),
        data_path=DEPENDENCIES_CATALOG,
    )
    # The only sglang entry carries ``lmcache 0.4.6rc1``, which ranks below the
    # bound, so no sglang service survives.
    assert [sr.service for sr in actual] == ["vllm"]

    strict = list_service_runners(
        dependencies=(("lmcache", ">=99.0"),),
        with_unknown_dependencies=False,
        data_path=DEPENDENCIES_CATALOG,
    )
    assert strict == []


def test_list_runners_rejects_unknown_keys():
    with pytest.raises(ValueError, match="Invalid keys in kwargs"):
        list_runners(unknown_key="whatever")


def test_runner_dependencies_is_optional():
    """
    An entry predating dependency probing keeps the field unset, and it must
    be omitted from the serialized form rather than serialized as null.
    """
    item = {
        "backend": "musa",
        "backend_version": "4.1",
        "original_backend_version": "4.1.0",
        "backend_variant": "",
        "service": "vllm",
        "service_version": "0.9.2",
        "platform": "linux/amd64",
        "docker_image": "gpustack/runner:musa4.1-vllm0.9.2",
        "deprecated": False,
    }
    runner = Runner.from_dict(item)
    assert runner.dependencies is None
    assert "dependencies" not in runner.to_dict()


def test_bundled_catalog_omits_absent_dependencies():
    """
    The ``dependencies`` field is optional: an unprobed entry serializes
    without the key rather than as null, a probed one carries the probed map.
    """
    runners = list_runners()
    assert runners, "expected a non-empty runner catalog"
    for r in runners:
        serialized = r.to_dict()
        if r.dependencies is None:
            assert "dependencies" not in serialized, (
                f"expected unprobed entry {r.docker_image} to serialize "
                f"without a dependencies key"
            )
        else:
            assert serialized["dependencies"] == r.dependencies


def test_bundled_catalog_is_lenient_by_default():
    """
    A dependency condition keeps unprobed bundled entries by default; strict
    mode drops them and keeps only probed entries satisfying the condition.
    """
    baseline = list_runners(backend="cuda", todict=True)
    assert baseline, "expected a non-empty cuda runner catalog"

    # An unsatisfiable condition isolates the unprobed-entry handling from the
    # version matching: no probed entry can satisfy it, so lenient mode keeps
    # exactly the unprobed entries and strict mode keeps nothing.
    conditions = (("lmcache", ">=99.0"),)
    unprobed = [r for r in baseline if "dependencies" not in r]

    lenient = list_runners(
        backend="cuda",
        dependencies=conditions,
        todict=True,
    )
    assert lenient == unprobed

    strict = list_runners(
        backend="cuda",
        dependencies=conditions,
        with_unknown_dependencies=False,
        todict=True,
    )
    assert strict == []


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
