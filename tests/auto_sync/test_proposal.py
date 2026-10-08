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
