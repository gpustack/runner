"""Discovery reads release identities and both default-branch detection sources."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.auto_sync.discovery import (
    DiscoveryError,
    _base,
    _read_sources,
    _represented,
    canonical_variant,
    discover,
    parse_support,
    prerelease_packages,
    version,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "discovery"
HEADER = """# Support records

<!-- runner-support-records:start -->
| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
{rows}<!-- runner-support-records:end -->
"""
# Detection also parses historical tables from the supported-runners guide. This
# stub never matches a subscribed combination, so fixture rows stay decisive.
HISTORY = """# Supported runners

### Iluvatar CoreX

| CoreX Version <br/> (Variant) | vLLM    |
|-------------------------------|---------|
| 4.2                           | `0.8.3` |
"""


def support_row(**changes):
    row = {
        "backend": "cuda",
        "runtime": "13.0",
        "service": "vllm",
        "variant": "-",
        "engine": "0.29.0",
        "plugin": "-",
        "platforms": "linux/amd64, linux/arm64",
        "status": "prepared",
        **changes,
    }
    return "| " + " | ".join(row.values()) + " |\n"


def catalog_row(**changes):
    return {
        "backend": "cuda",
        "backend_version": "13.0",
        "backend_variant": "",
        "service": "vllm",
        "service_version": "0.29.0",
        "platform": "linux/amd64",
        "docker_image": "gpustack/runner:example",
        **changes,
    }


def release(tag, **changes):
    return {"tag_name": tag, "draft": False, "prerelease": False, **changes}


@pytest.fixture
def upstream():
    return {
        "vllm-project/vllm": [release("v0.29.0"), release("v0.27.1")],
        "sgl-project/sglang": [release("v0.5.18")],
        "vllm-project/vllm-ascend": [release("v0.27.1rc1", prerelease=True)],
    }


@pytest.fixture
def pairs():
    return {
        "0.27.1rc1": {
            "engine_version": "0.27.1",
            "source": "https://github.com/vllm-project/vllm-ascend/releases/tag/v0.27.1rc1",
        },
    }


def repository(tmp_path, *, rows="", catalog=None):
    (tmp_path / "gpustack_runner").mkdir()
    (tmp_path / "gpustack_runner/runner.py.json").write_text(json.dumps(catalog or []))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/support-records.md").write_text(HEADER.format(rows=rows))
    (tmp_path / "docs/supported-runners.md").write_text(HISTORY)
    (tmp_path / "README.md").write_text(
        "[Supported runners](docs/supported-runners.md)\n",
    )
    return tmp_path


def selected(repo, upstream, pairs, name="cuda/vllm"):
    return next(
        row for row in discover(repo, upstream, pairs) if row["subscription"] == name
    )


def test_six_subscriptions_and_no_backlog(tmp_path, upstream, pairs):
    repo = repository(tmp_path, catalog=[catalog_row()])
    result = discover(repo, upstream, pairs)
    assert {row["subscription"] for row in result} == {
        "cuda/vllm",
        "cuda/sglang",
        "rocm/vllm",
        "rocm/sglang",
        "cann/vllm",
        "cann/sglang",
    }
    assert selected(repo, upstream, pairs)["status"] == "unchanged"
    assert selected(repo, upstream, pairs, "rocm/vllm")["status"] == "needs_update"
    assert selected(repo, upstream, pairs, "cann/vllm")["engine_version"] == "0.27.1"
    assert selected(repo, upstream, pairs, "cann/vllm")["plugin_version"] == "0.27.1rc1"
    assert [
        v["variant"] for v in selected(repo, upstream, pairs, "cann/vllm")["variants"]
    ] == ["950", "a3", "910b", "310p"]


@pytest.mark.parametrize(
    "source",
    ["catalog", "prepared", "published", "both", "neither"],
)
def test_either_source_prevents_repeat(tmp_path, upstream, pairs, source):
    repo = repository(
        tmp_path,
        catalog=[catalog_row(service_version="0.29")]
        if source in {"catalog", "both"}
        else [],
        rows=support_row(status="published" if source == "published" else "prepared")
        if source in {"prepared", "published", "both"}
        else "",
    )
    result = selected(repo, upstream, pairs)
    assert result["status"] == ("needs_update" if source == "neither" else "unchanged")
    assert (
        result["variants"][0]["sources"]
        == {
            "catalog": ["catalog"],
            "prepared": ["support"],
            "published": ["support"],
            "both": ["catalog", "support"],
            "neither": [],
        }[source]
    )


def test_newest_stable_post_not_api_order_or_unrelated_stream(
    tmp_path,
    upstream,
    pairs,
):
    upstream["vllm-project/vllm"] += [
        release("v0.30.0rc1", prerelease=True),
        release("v0.29.0.post1"),
        release("v0.29.1", draft=True),
        release("nightly"),
        release("v0.29.0+cuda"),
        release("v0.29.2", prerelease=True),
    ]
    repo = repository(tmp_path, rows=support_row())
    result = selected(repo, upstream, pairs)
    assert result["engine_version"] == "0.29.0.post1"
    assert result["status"] == "needs_update"


def test_chase_picks_next_line_not_newest(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] += [release("v0.30.1"), release("v0.31.0")]
    repo = repository(tmp_path, rows=support_row())
    result = selected(repo, upstream, pairs)
    assert result["engine_version"] == "0.30.1"
    assert result["current_version"] == "0.29.0"
    assert result["latest_version"] == "0.31.0"
    assert result["status"] == "needs_update"


def test_chase_picks_highest_post_within_next_line(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] += [
        release("v0.30.0"),
        release("v0.30.0.post1"),
        release("v0.31.0"),
    ]
    result = selected(repository(tmp_path, rows=support_row()), upstream, pairs)
    assert result["engine_version"] == "0.30.0.post1"


def test_chase_picks_patch_release_of_current_line_first(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] += [release("v0.29.1"), release("v0.30.0")]
    result = selected(repository(tmp_path, rows=support_row()), upstream, pairs)
    assert result["engine_version"] == "0.29.1"


def test_chase_without_records_picks_newest(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] += [release("v0.30.0"), release("v0.31.0")]
    result = selected(repository(tmp_path), upstream, pairs)
    assert result["engine_version"] == "0.31.0"
    assert result["current_version"] is None
    assert result["status"] == "needs_update"


def test_chase_cann_plugin_one_line_at_a_time(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] += [release("v0.23.0"), release("v0.24.0")]
    upstream["vllm-project/vllm-ascend"] += [
        release("v0.24.0rc1", prerelease=True),
    ]
    pairs["0.24.0rc1"] = {
        "engine_version": "0.24.0",
        "source": "https://github.com/vllm-project/vllm-ascend/releases/tag/v0.24.0rc1",
    }
    catalog = [
        catalog_row(
            backend="cann",
            backend_version="9.1",
            backend_variant=variant,
            service_version="0.23.0",
            dependencies={"vllm-ascend": "0.23.0"},
        )
        for variant in ["950", "a3", "910b", "310p"]
    ]
    result = selected(
        repository(tmp_path, catalog=catalog),
        upstream,
        pairs,
        "cann/vllm",
    )
    assert result["plugin_version"] == "0.24.0rc1"
    assert result["engine_version"] == "0.24.0"
    assert result["current_version"] == "0.23.0"
    assert result["latest_version"] == "0.27.1rc1"
    assert result["status"] == "needs_update"


def test_dropped_variant_is_not_chased(tmp_path, upstream, pairs):
    catalog = [
        catalog_row(
            backend="cann",
            backend_version="9.1",
            backend_variant=variant,
            service_version="0.27.1",
            dependencies={"vllm-ascend": "0.27.1rc1"},
        )
        for variant in ["950", "a3"]
    ]
    result = selected(
        repository(tmp_path, catalog=catalog),
        upstream,
        pairs,
        "cann/vllm",
    )
    assert [v["variant"] for v in result["variants"]] == ["950", "a3"]
    assert result["status"] == "unchanged"


def test_latest_ascend_without_pair_blocks_no_older_fallback(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm-ascend"].append(release("v0.29.0rc2", prerelease=True))
    result = selected(repository(tmp_path), upstream, pairs, "cann/vllm")
    assert result["status"] == "blocked"
    assert result["plugin_version"] == "0.29.0rc2"


@pytest.mark.parametrize("engine", ["0.27.1rc1", "0.30.0", "0.27.1.dev1"])
def test_pair_must_name_a_released_stable_engine(tmp_path, upstream, pairs, engine):
    pairs["0.27.1rc1"]["engine_version"] = engine
    assert (
        selected(repository(tmp_path), upstream, pairs, "cann/vllm")["status"]
        == "blocked"
    )


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("950", "950"),
        ("A5", "950"),
        ("950/A5", "950"),
        ("A3", "a3"),
        ("910C", "a3"),
        ("A3/910C", "a3"),
        ("910B", "910b"),
        ("310P", "310p"),
    ],
)
def test_explicit_cann_aliases(alias, canonical):
    assert canonical_variant("cann", alias) == canonical


def test_unknown_alias_is_not_guessed():
    with pytest.raises(DiscoveryError, match="variant"):
        canonical_variant("cann", "910")


def test_exact_plugin_and_variant_match(tmp_path, upstream, pairs):
    repo = repository(
        tmp_path,
        rows=support_row(
            backend="cann",
            runtime="9.1",
            variant="A5",
            engine="0.27.1",
            plugin="0.27.1rc1",
        ),
        catalog=[
            catalog_row(
                backend="cann",
                backend_variant="a3",
                service_version="0.27.1",
                dependencies={"vllm-ascend": "0.27.1rc2"},
            ),
        ],
    )
    # The variant universe follows current records: only 950 and a3 are
    # represented, so no other variant is chased.
    variants = selected(repo, upstream, pairs, "cann/vllm")["variants"]
    assert [v["variant"] for v in variants] == ["950", "a3"]
    assert variants[0]["status"] == "unchanged"
    assert variants[1]["status"] == "needs_update"


def test_legacy_rc_is_partial_identity_not_a_plugin_match(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] = [release("v0.20.2")]
    upstream["vllm-project/vllm-ascend"] = [release("v0.20.2rc1", prerelease=True)]
    pairs["0.20.2rc1"] = {**pairs["0.27.1rc1"], "engine_version": "0.20.2"}
    repo = repository(tmp_path)
    path = repo / "docs/supported-runners.md"
    # Prepend: text outside a parsed section is ignored, exactly like the
    # real guide's prose preamble ahead of its tables.
    path.write_text((FIXTURES / "legacy-support.md").read_text() + path.read_text())
    result = selected(repo, upstream, pairs, "cann/vllm")
    assert result["status"] == "needs_update"
    assert result["variants"][1]["insufficient_identity"] == ["support"]
    assert result["variants"][1]["sources"] == []


def test_raw_mentions_other_engine_backend_do_not_match(tmp_path, upstream, pairs):
    repo = repository(
        tmp_path,
        rows=support_row(backend="rocm"),
        catalog=[catalog_row(service="sglang")],
    )
    history = repo / "docs/supported-runners.md"
    # Prepend: the note stays outside the stub's parsed CoreX section.
    history.write_text(
        "\nWe considered cuda vllm 0.29.0 in release notes.\n" + history.read_text(),
    )
    assert selected(repo, upstream, pairs)["status"] == "needs_update"


@pytest.mark.parametrize(
    "broken",
    [
        "catalog_missing",
        "catalog_json",
        "catalog_shape",
        "records_missing",
        "records_table",
        "history_missing",
        "history_prose",
    ],
)
def test_failed_source_never_reports_unchanged(tmp_path, upstream, pairs, broken):
    repo = repository(tmp_path, rows=support_row(), catalog=[catalog_row()])
    catalog = repo / "gpustack_runner/runner.py.json"
    records = repo / "docs/support-records.md"
    history = repo / "docs/supported-runners.md"
    if broken == "catalog_missing":
        catalog.unlink()
    elif broken == "catalog_json":
        catalog.write_text("{")
    elif broken == "catalog_shape":
        catalog.write_text('[{"backend":"cuda"}]')
    elif broken == "records_missing":
        records.unlink()
    elif broken == "records_table":
        records.write_text(records.read_text().replace("prepared", "perhaps"))
    elif broken == "history_missing":
        history.unlink()
    else:
        history.write_text("A prose mention of cuda vllm 0.29.0 without tables.\n")
    assert {r["status"] for r in discover(repo, upstream, pairs)} == {"failed"}


@pytest.mark.parametrize(
    "broken",
    [None, {}, [{"tag_name": "v0.29.0"}], [release("v0.29.broken")]],
)
def test_upstream_failure_is_local_and_visible(tmp_path, upstream, pairs, broken):
    upstream["sgl-project/sglang"] = broken
    result = discover(repository(tmp_path), upstream, pairs)
    assert {r["status"] for r in result if r["service"] == "sglang"} == {"failed"}
    assert {r["status"] for r in result if r["service"] == "vllm"} == {"needs_update"}


def test_support_migration_preserves_every_original_cell():
    legacy = (FIXTURES / "legacy-support.md").read_text()
    support = (ROOT / "docs/supported-runners.md").read_text()

    def tables(text):
        # Bold annotations were dropped in the split and column padding was
        # re-flowed; whitespace-insensitive containment still proves that no
        # original table cell was lost.
        return " ".join(text.split("### Ascend CANN", 1)[1].replace("**", "").split())

    assert "### Ascend CANN" not in (ROOT / "README.md").read_text()
    assert tables(legacy) in tables(support)
    records = parse_support(support)
    assert [r for r in records if r["status"] == "historical"] == parse_support(legacy)
    assert {r["backend"] for r in records} == {
        "cann",
        "cuda",
        "rocm",
        "corex",
        "dtk",
        "hggc",
        "maca",
        "musa",
    }


def test_current_catalog_and_support_are_valid(upstream, pairs):
    results = discover(ROOT, upstream, pairs)
    assert all(r["status"] != "failed" for r in results)


@pytest.mark.parametrize("missing", [("start",), ("end",), ("start", "end")])
def test_linked_support_requires_markers_even_with_legacy_tables(
    tmp_path,
    upstream,
    pairs,
    missing,
):
    repo = repository(tmp_path)
    # The injected record must advance past every represented cuda/vllm
    # engine: a proposal branch legitimately records the former target, and
    # re-adding that identity here fails discovery with a duplicate support
    # identity. The catalog and legacy tables hold the represented versions,
    # so derive the target through the same sources discovery reads.
    records = (ROOT / "docs/support-records.md").read_text()
    sources = _read_sources(ROOT)
    base = _base(_represented(sources, "cuda", "vllm"), "cuda", "vllm")
    target = version(f"{base.major}.{base.minor + 1}.0")
    upstream["vllm-project/vllm"].append(release(f"v{target}"))
    path = repo / "docs/support-records.md"
    text = records.replace(
        "<!-- runner-support-records:end -->",
        support_row(engine=str(target)) + "<!-- runner-support-records:end -->",
    )
    path.write_text(text)
    assert selected(repo, upstream, pairs)["status"] == "unchanged"
    for marker in missing:
        text = text.replace(f"<!-- runner-support-records:{marker} -->", "")
    path.write_text(text)
    assert {r["status"] for r in discover(repo, upstream, pairs)} == {"failed"}


@pytest.mark.parametrize(
    "changes",
    [
        {"platforms": ""},
        {"platforms": "linux/amd64, linux/amd64"},
        {"plugin": "0.27.1rc1"},
        {"engine": "whatever"},
        {"runtime": "9.x"},
        {"backend": "unknown"},
        {"variant": "910b"},
        {"backend": "cann", "variant": "910b", "plugin": "-"},
    ],
)
def test_malformed_explicit_rows_rejected(changes):
    with pytest.raises(DiscoveryError):
        parse_support(HEADER.format(rows=support_row(**changes)))


def test_duplicate_explicit_identity_rejected():
    with pytest.raises(DiscoveryError, match="duplicate"):
        parse_support(
            HEADER.format(rows=support_row() + support_row(status="published")),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"platform": None},
        {"dependencies": []},
        {"service_version": None},
        {"backend_variant": "inferred"},
        {"dependencies": {"torch": None}},
    ],
)
def test_malformed_catalog_fields_return_failed(tmp_path, upstream, pairs, changes):
    result = discover(
        repository(tmp_path, catalog=[catalog_row(**changes)]),
        upstream,
        pairs,
    )
    assert {r["status"] for r in result} == {"failed"}


def test_support_symlink_cannot_escape_frozen_checkout(tmp_path, upstream, pairs):
    repo = tmp_path / "repo"
    repo.mkdir()
    repository(repo, catalog=[catalog_row()])
    outside = tmp_path / "outside.md"
    outside.write_text(HEADER.format(rows=support_row()))
    records = repo / "docs/support-records.md"
    records.unlink()
    records.symlink_to(outside)
    assert {r["status"] for r in discover(repo, upstream, pairs)} == {"failed"}


def test_catalog_can_resolve_unknown_historical_plugin(tmp_path, upstream, pairs):
    rows = [
        catalog_row(
            backend="cann",
            backend_variant=variant,
            service_version="0.27.1",
            dependencies={"vllm-ascend": "0.27.1rc1"},
        )
        for variant in ["950", "a3", "910b", "310p"]
    ]
    result = selected(repository(tmp_path, catalog=rows), upstream, pairs, "cann/vllm")
    assert result["status"] == "unchanged"
    assert all(v["sources"] == ["catalog"] for v in result["variants"])


def test_sglang_post_release_is_latest_for_all_backends(tmp_path, upstream, pairs):
    upstream["sgl-project/sglang"] += [
        release("v0.5.18.post1"),
        release("v0.5.19rc1", prerelease=True),
        release("sgl-kernel-v0.9.9"),
        release("v0.5.9"),
    ]
    result = discover(repository(tmp_path), upstream, pairs)
    assert {r["engine_version"] for r in result if r["service"] == "sglang"} == {
        "0.5.18.post1",
    }


def test_empty_release_query_blocks_instead_of_unchanged(tmp_path, upstream, pairs):
    upstream["vllm-project/vllm"] = []
    assert selected(repository(tmp_path), upstream, pairs)["status"] == "blocked"


def whitelisted(repo, text):
    path = repo / "pack" / "prereleases.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_prerelease_whitelist_is_sorted_and_absent_file_keeps_stable_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert prerelease_packages(repo) == []
    whitelisted(repo, "packages: [vllm-omni, lmcache, lmcache]\n")
    assert prerelease_packages(repo) == ["lmcache", "vllm-omni"]
    whitelisted(repo, "packages: []\n")
    assert prerelease_packages(repo) == []


@pytest.mark.parametrize(
    "text",
    [
        "packages: [lmcache, unknown-key]\n",
        "packages: lmcache\n",
        "other: [lmcache]\n",
        "packages: [lmcache]\nextra: true\n",
        "packages: [LMCache]\n",
        "packages: [[lmcache]]\n",
        "packages: [{key: lmcache}]\n",
        "packages: [",
    ],
)
def test_malformed_prerelease_whitelist_fails_preparation(tmp_path, text):
    repo = tmp_path / "repo"
    repo.mkdir()
    whitelisted(repo, text)
    with pytest.raises(DiscoveryError, match="prerelease whitelist"):
        prerelease_packages(repo)
