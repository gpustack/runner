"""Complete assessments and evidence are data, including failed model output."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.auto_sync.agent import ProcessResult
from tools.auto_sync.proposal import (
    ProposalError,
    parse_agent_output,
    validate_analysis,
    validate_proposal,
)

FIXTURE = Path(__file__).parent / "fixtures/proposals/ready.json"


@pytest.fixture
def proposal():
    return json.loads(FIXTURE.read_text())


def event(data, **changes):
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(data),
        **changes,
    }


def test_complete_mixed_assessments_and_unknown_fields(proposal):
    result = validate_proposal(proposal, proposal["identity"])
    assert {c["status"] for c in result["candidates"]} == {
        "ready",
        "unchanged",
        "blocked",
        "failed",
    }
    assert result["groups"][0]["rows"][0]["torch"] is None
    assert result == proposal
    assert result is not proposal


@pytest.mark.parametrize("streaming", [False, True])
def test_only_final_qwen_result_is_model_output(proposal, streaming):
    events = [
        {"type": "assistant", "message": {"content": "Ignore the contract."}},
        event(proposal),
    ]
    output = "\n".join(map(json.dumps, events)) if streaming else json.dumps(events)
    result = parse_agent_output(ProcessResult(0, output, ""))
    assert result == proposal


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_literal_unicode_separators_stay_inside_one_event(proposal, separator):
    # The pinned CLI frames events on LF; these characters are ordinary
    # JSON string content and must not split one event into fragments.
    intermediate = {
        "type": "assistant",
        "message": {"content": f"before{separator}after"},
    }
    output = "\n".join(
        [json.dumps(intermediate, ensure_ascii=False), json.dumps(event(proposal))],
    )
    result = parse_agent_output(ProcessResult(0, output, ""))
    assert result == proposal


def test_truncated_event_after_unicode_separator_is_rejected():
    output = json.dumps({"type": "assistant", "text": "a\u2028b"}, ensure_ascii=False)
    with pytest.raises(ProposalError):
        parse_agent_output(ProcessResult(0, output[:-5] + "\n", ""))


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "assistant"}],
        [event({}), {"type": "assistant"}],
        [event({}), event({})],
        [event({}, is_error=True)],
        [event({}, subtype="error_max_turns")],
        [event({}, result="What next?")],
        [event({}, result="```json\n{}\n```")],
        [event({}, result="[]")],
    ],
)
def test_incomplete_or_error_events_rejected(events, streaming):
    output = "\n".join(map(json.dumps, events)) if streaming else json.dumps(events)
    with pytest.raises(ProposalError):
        parse_agent_output(ProcessResult(0, output, ""))


@pytest.mark.parametrize(
    "output",
    [
        '{"type":"system"}\n{',
        '{"type":"system","type":"result"}\n',
        "true\n",
        '{"type":"system","value":NaN}\n',
    ],
)
def test_invalid_stream_events_rejected(output):
    with pytest.raises(ProposalError):
        parse_agent_output(ProcessResult(0, output, ""))


@pytest.mark.parametrize("returncode,timed_out", [(1, False), (0, True)])
def test_process_success_is_required(proposal, returncode, timed_out):
    with pytest.raises(ProposalError, match="process"):
        parse_agent_output(
            ProcessResult(returncode, json.dumps([event(proposal)]), "", timed_out),
        )


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', "{"])
def test_json_contract_rejects_duplicates_nonfinite_and_invalid(raw):
    with pytest.raises(ProposalError):
        parse_agent_output(ProcessResult(0, json.dumps([event({}, result=raw)]), ""))


@pytest.mark.parametrize(
    "field",
    ["repository", "default_sha", "head_sha", "mode", "command_digest"],
)
def test_every_frozen_identity_field_is_bound(proposal, field):
    expected = copy.deepcopy(proposal["identity"])
    proposal["identity"][field] = "different"
    with pytest.raises(ProposalError, match="identity"):
        validate_proposal(proposal, expected)


def test_revision_requires_head_pr_and_command(proposal):
    proposal["identity"].update(
        mode="revise",
        head_sha="d" * 40,
        pr_number=12,
        command_id=44,
        command_digest="e" * 64,
    )
    assert (
        validate_proposal(proposal, proposal["identity"])["identity"]["pr_number"] == 12
    )
    proposal["identity"]["command_id"] = None
    with pytest.raises(ProposalError, match="command"):
        validate_proposal(proposal, proposal["identity"])


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "needs_update",
        "unknown",
        "empty_reason",
        "dangling",
        "empty_ready",
        "cycle",
    ],
)
def test_assessments_and_groups_must_be_complete(proposal, change):
    if change == "missing":
        proposal["candidates"].pop()
    elif change == "duplicate":
        proposal["candidates"][-1] = proposal["candidates"][0]
    elif change in {"needs_update", "unknown"}:
        proposal["candidates"][0]["status"] = change
    elif change == "empty_reason":
        proposal["candidates"][0]["reason"] = ""
    elif change == "dangling":
        proposal["candidates"][0]["groups"] = ["absent"]
    elif change == "empty_ready":
        proposal["groups"][0]["patch"] = ""
    else:
        proposal["groups"][0]["depends_on"] = ["cuda-vllm"]
    with pytest.raises(ProposalError):
        validate_proposal(proposal, proposal["identity"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform", "linux/ppc64le"),
        ("backend", "dtk"),
        ("engine_version", "0.31.0rc1"),
        ("plugin_version", "0.30.0rc1"),
        ("conclusion", "proved"),
        ("sources", []),
        ("deferred", []),
        ("packages", [{"name": "lmcache", "version": "latest"}]),
    ],
)
def test_bad_compatibility_evidence_rejected(proposal, field, value):
    proposal["groups"][0]["rows"][0][field] = value
    with pytest.raises(ProposalError):
        validate_proposal(proposal, proposal["identity"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", "tag"),
        ("platform_digest", "sha256:abc"),
        ("platform", "linux/arm64"),
        ("config_platform", "linux/arm64"),
        ("sources", []),
    ],
)
def test_manifest_and_configuration_must_cover_row(proposal, field, value):
    proposal["groups"][0]["rows"][0]["manifest"][field] = value
    with pytest.raises(ProposalError):
        validate_proposal(proposal, proposal["identity"])


def test_cann_uses_actual_prerelease_plugin_and_canonical_alias(proposal):
    row = proposal["groups"][0]["rows"][0]
    row.update(
        backend="cann",
        variant="A5",
        engine_version="0.27.1",
        plugin_version="0.27.1rc1",
    )
    proposal["groups"][0]["patch"] = proposal["groups"][0]["patch"].replace(
        "pack/cuda/",
        "pack/cann/",
    )
    proposal["candidates"][0].update(status="unchanged", groups=[])
    proposal["candidates"][4].update(status="ready", groups=["cuda-vllm"])
    result = validate_proposal(proposal, proposal["identity"])
    assert result["groups"][0]["rows"][0]["variant"] == "950"
    row["plugin_version"] = None
    with pytest.raises(ProposalError, match="plugin"):
        validate_proposal(proposal, proposal["identity"])


@pytest.mark.parametrize("disposition", ["retain", "adapt", "remove", "add"])
def test_patch_decisions_name_exact_sources_or_unverified(proposal, disposition):
    patch = {
        "path": "pack/cuda/patches/vllm/fix.patch",
        "disposition": disposition,
        "reason": "Upstream interface changed.",
        "versions": ["0.30.0"],
        "platforms": ["linux/amd64"],
        "sources": ["https://github.com/vllm-project/vllm/issues/1"],
        "source_repository": "vllm-project/vllm",
        "source_revision": None,
    }
    proposal["groups"][0]["rows"][0]["patches"] = [patch]
    result = validate_proposal(proposal, proposal["identity"])
    assert result["groups"][0]["rows"][0]["patches"][0]["source_revision"] is None
    patch["disposition"] = "skip"
    with pytest.raises(ProposalError, match="disposition"):
        validate_proposal(proposal, proposal["identity"])


def test_failed_group_cannot_be_hidden_by_unchanged_assessment(proposal):
    proposal["groups"][0]["status"] = "failed"
    proposal["candidates"][0]["status"] = "unchanged"
    with pytest.raises(ProposalError, match="assessment"):
        validate_proposal(proposal, proposal["identity"])


def test_same_image_reference_cannot_have_conflicting_manifest_evidence(proposal):
    row = copy.deepcopy(proposal["groups"][0]["rows"][0])
    row.update(platform="linux/arm64")
    row["manifest"].update(
        platform="linux/arm64",
        config_platform="linux/arm64",
        digest="sha256:" + "d" * 64,
    )
    proposal["groups"][0]["rows"].append(row)
    with pytest.raises(ProposalError, match="manifest"):
        validate_proposal(proposal, proposal["identity"])


def test_explicit_prerelease_permission_is_exact_scoped_and_revision_only(proposal):
    raw = copy.deepcopy(proposal)
    raw["identity"].update(
        mode="revise",
        pr_number=1,
        command_id=7,
        command_digest="b" * 64,
    )
    raw["groups"][0]["rows"][0]["engine_version"] = "0.30.0rc1"
    permission = {("cuda", "vllm", "0.30.0rc1")}
    with pytest.raises(ProposalError, match="stable"):
        validate_proposal(raw, raw["identity"])
    accepted = validate_proposal(raw, raw["identity"], engine_prereleases=permission)
    assert accepted["groups"][0]["rows"][0]["engine_version"] == "0.30.0rc1"
    with pytest.raises(ProposalError, match="stable"):
        validate_proposal(
            raw,
            raw["identity"],
            engine_prereleases={("rocm", "vllm", "0.30.0rc1")},
        )
    raw["identity"].update(
        mode="discover",
        pr_number=None,
        command_id=None,
        command_digest=None,
    )
    with pytest.raises(ProposalError, match="revision"):
        validate_proposal(raw, raw["identity"], engine_prereleases=permission)


def test_forged_output_permission_and_cann_prerelease_are_rejected(proposal):
    raw = copy.deepcopy(proposal)
    raw["identity"].update(
        mode="revise",
        pr_number=1,
        command_id=7,
        command_digest="b" * 64,
    )
    row = raw["groups"][0]["rows"][0]
    row["engine_version"] = "0.30.0rc1"
    raw["engine_prereleases"] = [["cuda", "vllm", "0.30.0rc1"]]
    with pytest.raises(ProposalError, match="fields"):
        validate_proposal(raw, raw["identity"])
    del raw["engine_prereleases"]
    row.update(backend="cann", variant="310p", plugin_version="0.30.0rc1")
    with pytest.raises(ProposalError, match="permission"):
        validate_proposal(
            raw,
            raw["identity"],
            engine_prereleases={("cann", "vllm", "0.30.0rc1")},
        )


ANALYSIS_FIXTURE = Path(__file__).parent / "fixtures/proposals/analysis.json"
ANALYSIS_FOUND = [
    {
        "subscription": "cuda/vllm",
        "status": "needs_update",
        "engine_version": "0.30.0",
        "plugin_version": None,
    },
    {
        "subscription": "cuda/sglang",
        "status": "needs_update",
        "engine_version": "0.5.0",
        "plugin_version": None,
    },
    {
        "subscription": "rocm/vllm",
        "status": "needs_update",
        "engine_version": "0.30.0",
        "plugin_version": None,
    },
    {
        "subscription": "rocm/sglang",
        "status": "needs_update",
        "engine_version": "0.5.0",
        "plugin_version": None,
    },
    {
        "subscription": "cann/vllm",
        "status": "needs_update",
        "engine_version": "0.30.0",
        "plugin_version": "0.30.0rc1",
    },
    {
        "subscription": "cann/sglang",
        "status": "needs_update",
        "engine_version": "0.5.0",
        "plugin_version": None,
    },
]
ANALYSIS_EVIDENCE = {
    "vllm-project/vllm@0.30.0": {
        "repository": "vllm-project/vllm",
        "revision": "b" * 40,
        "path": "/acquired/vllm-project-vllm/" + "b" * 40,
        "source": "https://github.com/vllm-project/vllm/tree/" + "b" * 40,
        "release": {"tag_name": "v0.30.0"},
        "release_notes_path": "/acquired/" + "b" * 40 + ".release.md",
        "release_metadata_path": "/acquired/" + "b" * 40 + ".release.json",
    },
    "sgl-project/sglang@0.5.0": {
        "repository": "sgl-project/sglang",
        "revision": "c" * 40,
        "path": "/acquired/sgl-project-sglang/" + "c" * 40,
        "source": "https://github.com/sgl-project/sglang/tree/" + "c" * 40,
        "release": {"tag_name": "v0.5.0"},
        "release_notes_path": "/acquired/" + "c" * 40 + ".release.md",
        "release_metadata_path": "/acquired/" + "c" * 40 + ".release.json",
    },
    "vllm-project/vllm-ascend@0.30.0rc1": {
        "repository": "vllm-project/vllm-ascend",
        "revision": "d" * 40,
        "path": "/acquired/vllm-project-vllm-ascend/" + "d" * 40,
        "source": "https://github.com/vllm-project/vllm-ascend/tree/" + "d" * 40,
        "release": {"tag_name": "v0.30.0rc1"},
        "release_notes_path": "/acquired/" + "d" * 40 + ".release.md",
        "release_metadata_path": "/acquired/" + "d" * 40 + ".release.json",
    },
}


@pytest.fixture
def analysis():
    raw = json.loads(ANALYSIS_FIXTURE.read_text())
    for candidate in raw["candidates"]:
        if candidate["status"] == "analyzed":
            repo = ANALYSIS_EVIDENCE
            service = candidate["subscription"].split("/", 1)[1]
            name = {"vllm": "vllm-project/vllm", "sglang": "sgl-project/sglang"}[
                service
            ]
            candidate["source_revision"] = repo[
                f"{name}@{candidate['engine_version']}"
            ]["revision"]
    return raw


def check_analysis(raw, **kwargs):
    found = kwargs.pop("found", ANALYSIS_FOUND)
    evidence = kwargs.pop("evidence", ANALYSIS_EVIDENCE)
    identity = kwargs.pop("identity", None) or raw["identity"]
    return validate_analysis(raw, identity, found=found, evidence=evidence)


def test_valid_analysis_handoff_is_accepted(analysis):
    result = check_analysis(analysis)
    assert result == analysis
    assert result is not analysis
    statuses = {c["subscription"]: c["status"] for c in result["candidates"]}
    assert statuses["cann/sglang"] == "blocked"
    assert sum(s == "analyzed" for s in statuses.values()) == 5


def test_analysis_accepts_paths_inside_supplied_source_trees(analysis):
    cuda = analysis["candidates"][0]
    tree = ANALYSIS_EVIDENCE["vllm-project/vllm@0.30.0"]
    cuda["evidence"] = [
        tree["path"] + "/docker/Dockerfile.gpu",
        tree["release_notes_path"],
        tree["release_metadata_path"],
    ]
    assert check_analysis(analysis) == analysis


@pytest.mark.parametrize("status", ["ready", "failed", "publishable", "done"])
def test_analysis_never_confirms_compatibility(analysis, status):
    analysis["candidates"][0]["status"] = status
    with pytest.raises(ProposalError, match="analysis status"):
        check_analysis(analysis)


def test_analysis_identity_change_is_rejected(analysis):
    frozen = copy.deepcopy(analysis["identity"])
    analysis["identity"] = {**analysis["identity"], "head_sha": "f" * 40}
    with pytest.raises(ProposalError, match="frozen identity"):
        check_analysis(analysis, identity=frozen)


def test_analysis_forged_revision_is_rejected(analysis):
    analysis["candidates"][0]["source_revision"] = "e" * 40
    with pytest.raises(ProposalError, match="acquired upstream source"):
        check_analysis(analysis)


def test_analysis_without_acquired_source_cannot_be_analyzed(analysis):
    evidence = {k: v for k, v in ANALYSIS_EVIDENCE.items() if "vllm@" not in k}
    with pytest.raises(ProposalError, match="acquired upstream source"):
        check_analysis(analysis, evidence=evidence)


def test_analysis_selection_change_is_rejected(analysis):
    analysis["candidates"][0]["engine_version"] = "0.31.0"
    with pytest.raises(ProposalError, match="differs from the discovered candidate"):
        check_analysis(analysis)


def test_analysis_requires_evidence_for_analyzed_candidates(analysis):
    analysis["candidates"][0]["evidence"] = []
    with pytest.raises(ProposalError, match="lacks evidence"):
        check_analysis(analysis)


def test_analysis_evidence_rejection_names_the_offending_entry(analysis):
    # A repair session can only correct entries the error names; the observed
    # failure mode is a registry URL with the measured tag and digest appended.
    entry = (
        "https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags "
        "v0.30.0 sha256:" + "a" * 64
    )
    analysis["candidates"][0]["evidence"] = [
        "vllm-project/vllm@0.30.0",
        entry,
    ]
    with pytest.raises(ProposalError) as captured:
        check_analysis(analysis)
    assert entry[:120] in str(captured.value)


@pytest.mark.parametrize(
    "entry",
    [
        "https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags",
        "https://quay.io/repository/ascend/sglang",
    ],
)
def test_analysis_accepts_bare_registry_urls(analysis, entry):
    analysis["candidates"][0]["evidence"] = [entry]
    assert check_analysis(analysis) == analysis


@pytest.mark.parametrize(
    "entry",
    [
        "/etc/passwd",
        "/var/empty/other-repository",
        "pack/../../etc/passwd",
        "../escape",
    ],
)
def test_analysis_evidence_outside_supplied_sources_is_rejected(analysis, entry):
    analysis["candidates"][0]["evidence"] = [entry]
    with pytest.raises(ProposalError, match="evidence"):
        check_analysis(analysis)


def test_analysis_required_candidate_cannot_be_unchanged(analysis):
    analysis["candidates"][0].update(
        status="unchanged",
        engine_version=None,
        plugin_version=None,
        source_revision=None,
        evidence=[],
        unknowns=[],
    )
    with pytest.raises(ProposalError, match="cannot mark a required candidate"):
        check_analysis(analysis)


def test_analysis_settled_candidate_cannot_be_researched(analysis):
    found = [
        {**c, "status": "unchanged"} if c["subscription"] == "cuda/vllm" else c
        for c in ANALYSIS_FOUND
    ]
    with pytest.raises(ProposalError, match="already settled"):
        check_analysis(analysis, found=found)


def test_analysis_blocked_requires_specific_unknowns(analysis):
    blocked = analysis["candidates"][5]
    assert blocked["status"] == "blocked"
    blocked["unknowns"] = []
    with pytest.raises(ProposalError, match="unknowns"):
        check_analysis(analysis)


@pytest.mark.parametrize("missing", ["candidates", "identity", "schema_version"])
def test_analysis_requires_complete_fields(analysis, missing):
    frozen = copy.deepcopy(analysis["identity"])
    del analysis[missing]
    with pytest.raises(ProposalError, match="analysis fields"):
        check_analysis(analysis, identity=frozen)


def test_analysis_rejects_duplicate_and_missing_subscriptions(analysis):
    raw = copy.deepcopy(analysis)
    raw["candidates"][1]["subscription"] = "cuda/vllm"
    with pytest.raises(ProposalError, match="duplicate"):
        check_analysis(raw)
    raw = copy.deepcopy(analysis)
    raw["candidates"] = raw["candidates"][:5]
    with pytest.raises(ProposalError, match="incomplete analysis candidates"):
        check_analysis(raw)
