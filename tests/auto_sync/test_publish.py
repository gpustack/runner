"""Publication uses real Git objects and a stateful local GitHub HTTP fixture."""

import copy
import difflib
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent / "fixtures/github"))
from service import FakeGitHub

from tools.auto_sync import publish as publication
from tools.auto_sync.checks import report_digest, validate_candidate, verify_artifact
from tools.auto_sync.publish import BRANCH, GitHub, prepare_context, publish

SUPPORT = "docs/support-records.md"
BOT = "runner-sync[bot]"
REPOSITORY = "gpustack/runner"


def git(repo, *args):
    return subprocess.run(  # noqa: S603 - disposable fixture repositories only.
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],  # noqa: S607 - fixture Git objects only.
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def scenario(tmp_path):
    repo = tmp_path / "objects"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "pack/cuda").mkdir(parents=True)
    (repo / "pack/cuda/Dockerfile.vllm").write_text(
        "ARG VLLM_VERSION=0.29.0\nARG CUDA_VERSION=13.0.1\nARG VLLM_BASE_IMAGE=vllm/vllm-openai:v${VLLM_VERSION}\nARG PYTHON_VERSION=3.12\nARG VLLM_LMCACHE_VERSION=0.5.4\nFROM ${VLLM_BASE_IMAGE} AS vllm\n",
    )
    (repo / "pack/matrix.yaml").write_text(
        "rules:\n  - backend: cuda\n    services: [vllm]\n    platforms: [linux/amd64]\n    args: [VLLM_VERSION=0.29.0]\n",
    )
    (repo / "README.md").write_text(
        "# Runner\n[Supported runners](docs/supported-runners.md)\n",
    )
    (repo / "docs").mkdir()
    (repo / SUPPORT).write_text(
        "<!-- runner-support-records:start -->\n| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| cuda | 13.0 | vllm | - | 0.29.0 | - | linux/amd64 | prepared |\n<!-- runner-support-records:end -->\n",
    )
    (repo / "docs/release-automation.md").write_text(
        "Keep LMCache at 0.5.4 for CUDA/vLLM. Reconsider after protocol review.\n",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture baseline")
    sha = git(repo, "rev-parse", "HEAD")
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    raw["identity"].update(default_sha=sha, head_sha=sha)
    with FakeGitHub(repo, REPOSITORY, BOT) as service:
        api = GitHub("fake-write-token", BOT, api_url=service.url)
        context = prepare_context(api, REPOSITORY, sha)
        artifact = validate_candidate(repo, raw, context["identity"])
        yield repo, service, api, context, artifact


def initial(scenario):
    repo, _, api, context, artifact = scenario
    result = publish(api, repo, context, artifact)
    assert result["status"] == "published"
    return result


def revision(
    scenario,
    body="/auto-sync\nUpdate the report. Keep all versions unchanged.",
):
    repo, service, api, _, _ = scenario
    event = service.comment_event(body)
    context = prepare_context(api, REPOSITORY, git(repo, "rev-parse", "main"), event)
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    raw["identity"] = context["identity"]
    group = raw["groups"][0]
    group["rows"][0]["old_engine_version"] = "0.30.0"
    group["patch"] = (
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,2 +1,3 @@\n # Runner\n [Supported runners](docs/supported-runners.md)\n+Release report was reviewed.\n"
    )
    artifact = validate_candidate(repo, raw, context["identity"])
    assert artifact["patch"]
    return event, context, artifact


def source_candidate(scenario, tmp_path, mode, *, incompatible=False):
    repo, _, _, context, artifact = scenario
    if mode == "revise":
        initial(scenario)
        _, context, artifact = revision(scenario)
    source = tmp_path / "upstream"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    (source / "engine.py").write_text("value = 9\n" if incompatible else "value = 1\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "selected source")
    raw = verify_artifact(artifact, context["identity"])
    path = "pack/cuda/patches/vllm/fix.patch"
    patch = "diff --git a/engine.py b/engine.py\n--- a/engine.py\n+++ b/engine.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    raw["groups"][0]["patch"] += (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        + "".join(
            difflib.unified_diff(
                [],
                patch.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile="b/" + path,
            ),
        )
    )
    raw["groups"][0]["rows"][0]["patches"] = [
        {
            "path": path,
            "disposition": "add",
            "reason": "Apply the compatibility fix to the selected source.",
            "versions": ["0.30.0"],
            "platforms": ["linux/amd64"],
            "sources": ["https://github.com/vllm-project/vllm/issues/1"],
            "source_repository": "vllm-project/vllm",
            "source_revision": git(source, "rev-parse", "HEAD"),
        },
    ]
    artifact = validate_candidate(repo, raw, context["identity"])
    assert artifact["patch"] == raw["groups"][0]["patch"]
    assert artifact["groups"][0]["validation"]["patches"][0]["status"] == "unverified"
    return context, artifact, {"vllm-project/vllm": source}


def interrupt_report(service, monkeypatch, mode):
    original = service.request
    route = (
        "/repos/"
        + REPOSITORY
        + ("/issues/1/comments" if mode == "revise" else "/pulls")
    )

    def request(method, path, body):
        if method == "POST" and path == route:
            monkeypatch.setattr(service, "request", original)
            return 500, {"message": "Report interrupted before visible reply."}
        return original(method, path, body)

    monkeypatch.setattr(service, "request", request)


def test_formal_single_pr_stable_identity_and_complete_mixed_report(scenario):
    repo, service, _, context, artifact = scenario
    result = initial(scenario)
    assert len(service.prs) == 1
    pr = service.prs[1]
    assert not pr["draft"]
    assert pr["head"]["ref"] == BRANCH
    assert pr["user"]["login"] == BOT
    assert git(repo, "rev-parse", BRANCH + "^") == context["identity"]["head_sha"]
    assert git(repo, "show", BRANCH + ":pack/cuda/Dockerfile.vllm").startswith(
        "ARG VLLM_VERSION=0.30.0",
    )
    assert result["checked"] == artifact
    for word in (
        "ready",
        "blocked",
        "failed",
        "0.29.0",
        "0.30.0",
        "linux/amd64",
        "sha256:",
        "unverified",
    ):
        assert word in pr["body"]
    assert git(repo, "status", "--porcelain") == ""


def test_weekly_and_manual_defer_any_older_managed_proposal_without_writes(scenario):
    _, service, api, context, artifact = scenario
    initial(scenario)
    service.prs[1]["head"]["ref"] = "auto-sync/older-proposal"
    before = copy.deepcopy(service.prs)
    service.requests.clear()
    next_run = prepare_context(api, REPOSITORY, context["identity"]["default_sha"])
    assert next_run["status"] == "deferred"
    result = publish(api, scenario[0], next_run, artifact)
    assert result["status"] == "deferred"
    assert result["checked"]["candidates"] == artifact["candidates"]
    assert service.prs == before
    assert all(method == "GET" for method, _, _ in service.requests)


@pytest.mark.parametrize("author", ["maintainer", None])
def test_revision_restores_current_context_and_preserves_human_work_and_pins(
    scenario,
    author,
):
    repo, service, api, _, _ = scenario
    initial(scenario)
    human = service.human_commit("human.txt", "Do not replace direct human work.\n")
    service.authors[human] = author
    service.reviews = [
        {"id": 8, "body": "Keep the engine upgrade.", "state": "CHANGES_REQUESTED"},
    ]
    service.inline = [{"id": 9, "body": "Review the compatibility evidence."}]
    _, context, artifact = revision(scenario)
    assert context["identity"]["head_sha"] == human
    assert context["reviews"] == service.reviews
    assert context["review_comments"] == service.inline
    assert context["diff"]
    assert context["comments"]
    assert "0.5.4" in context["constraints"]["docs/release-automation.md"]
    result = publish(api, repo, context, artifact)
    assert result["status"] == "published"
    assert git(repo, "rev-parse", BRANCH + "^") == human
    assert (
        git(repo, "show", BRANCH + ":human.txt") == "Do not replace direct human work."
    )
    assert "0.5.4" in git(repo, "show", BRANCH + ":docs/release-automation.md")
    assert "0.30.0" in git(repo, "show", BRANCH + ":pack/cuda/Dockerfile.vllm")
    assert len(service.prs) == 1
    assert service.comments[-1]["user"]["login"] == BOT
    assert result["commit_sha"] in service.comments[-1]["body"]
    assert all(
        body.get("force") is False
        for method, path, body in service.requests
        if method == "PATCH" and "/git/refs/" in path
    )


@pytest.mark.parametrize("permission", ["read", "triage", "none"])
def test_unauthorized_conversation_commands_never_start_research(scenario, permission):
    _, service, api, context, _ = scenario
    initial(scenario)
    event = service.comment_event("/auto-sync\nPin LMCache to 0.5.4.")
    service.permission = permission
    service.requests.clear()
    result = prepare_context(api, REPOSITORY, context["identity"]["default_sha"], event)
    assert result["status"] == "ignored"
    assert "identity" not in result
    assert all(method == "GET" for method, _, _ in service.requests)


@pytest.mark.parametrize(
    "change",
    ["edited", "inline", "bot", "ordinary", "fork", "closed", "foreign"],
)
def test_wrong_trigger_or_ownership_rejected(scenario, change):
    _, service, api, context, _ = scenario
    initial(scenario)
    event = service.comment_event("/auto-sync\nUpdate report.")
    if change == "edited":
        event["action"] = "edited"
    elif change == "inline":
        event["issue"].pop("pull_request")
    elif change == "bot":
        service.comments[-1]["user"] = {"login": BOT, "type": "Bot"}
        event["comment"] = copy.deepcopy(service.comments[-1])
    elif change == "ordinary":
        service.comments[-1]["body"] = "Please review."
        event["comment"] = copy.deepcopy(service.comments[-1])
    elif change == "fork":
        service.prs[1]["head"]["repo"]["full_name"] = "attacker/runner"
    elif change == "closed":
        service.prs[1]["state"] = "closed"
    elif change == "foreign":
        service.prs[1]["user"]["login"] = "other-bot[bot]"
    result = prepare_context(api, REPOSITORY, context["identity"]["default_sha"], event)
    assert result["status"] in {"ignored", "deferred"}


def test_changed_comment_and_changed_head_rejected_before_push(scenario):
    repo, service, api, _, _ = scenario
    initial(scenario)
    event, context, artifact = revision(scenario)
    service.comments[-1]["body"] += "\nChange engine too."
    result = publish(api, repo, context, artifact)
    assert result["status"] == "deferred"
    assert result["checked"]["patch"] == artifact["patch"]
    service.comments[-1]["body"] = event["comment"]["body"]
    human = service.human_commit("human.txt", "New concurrent work.\n")
    result = publish(api, repo, context, artifact)
    assert result["status"] == "deferred"
    assert git(repo, "rev-parse", BRANCH) == human


def test_non_fast_forward_race_does_not_overwrite_human_commit(scenario):
    repo, service, api, _, _ = scenario
    initial(scenario)
    _, context, artifact = revision(scenario)
    service.before_ref_update = lambda: service.human_commit(
        "race.txt",
        "Concurrent work.\n",
    )
    result = publish(api, repo, context, artifact)
    assert result["status"] == "deferred"
    assert git(repo, "show", BRANCH + ":race.txt") == "Concurrent work."
    assert "Release report was reviewed." not in git(
        repo,
        "show",
        BRANCH + ":README.md",
    )


@pytest.mark.parametrize("point", ["ref", "pr", "report"])
def test_partial_publication_retry_adopts_landed_state(scenario, point):
    repo, service, api, context, artifact = scenario
    if point == "report":
        initial(scenario)
        _, context, artifact = revision(scenario)
    service.fail_after = point
    failed = publish(api, repo, context, artifact)
    assert failed["status"] == "failed"
    landed = git(repo, "rev-parse", BRANCH)
    result = publish(api, repo, context, artifact)
    assert result["status"] in {"published", "duplicate", "deferred"}
    assert git(repo, "rev-parse", BRANCH) == landed
    assert len(service.prs) == 1
    if point == "report":
        assert context["identity"]["command_digest"] in service.comments[-1]["body"]


@pytest.mark.parametrize("mode", ["discover", "revise"])
def test_retry_preserves_report_identity_after_source_becomes_available(
    scenario,
    tmp_path,
    monkeypatch,
    mode,
):
    repo, service, api, _, _ = scenario
    context, artifact, sources = source_candidate(scenario, tmp_path, mode)
    original = copy.deepcopy(artifact)
    interrupt_report(service, monkeypatch, mode)
    failed = publish(api, repo, context, artifact)
    assert failed["status"] == "failed"
    landed = git(repo, "rev-parse", BRANCH)
    assert git(repo, "rev-parse", landed + "^") == context["identity"]["head_sha"]
    assert not any(c["user"]["login"] == BOT for c in service.comments)
    if mode == "discover":
        assert not service.prs
    service.requests.clear()
    recovered = publish(api, repo, context, artifact, sources=sources)
    assert recovered["status"] == ("duplicate" if mode == "revise" else "published")
    assert recovered["commit_sha"] == landed
    assert recovered["checked"] == original == artifact
    fresh = recovered["revalidation"]
    assert fresh["groups"][0]["validation"]["patches"][0]["status"] == "passed"
    assert fresh["patch"] == original["patch"]
    assert fresh["report_digest"] != original["report_digest"]
    record = json.loads(
        git(repo, "show", "-s", "--format=%B", landed)
        .splitlines()[2]
        .removeprefix(publication.COMMIT_MARKER),
    )
    assert record["report_digest"] == original["report_digest"]
    assert git(repo, "rev-parse", BRANCH) == landed
    assert not any(
        method != "GET" and "/git/" in path for method, path, _ in service.requests
    )
    assert len(service.prs) == 1
    assert git(sources["vllm-project/vllm"], "status", "--porcelain") == ""
    if mode == "revise":
        replies = [c for c in service.comments if c["user"]["login"] == BOT]
        assert len(replies) == 1
        reply_record = json.loads(
            replies[0]["body"]
            .splitlines()[0]
            .removeprefix(publication.MARKER)
            .removesuffix(" -->"),
        )
        assert reply_record["report_digest"] == original["report_digest"]
        assert (
            prepare_context(
                api,
                REPOSITORY,
                context["identity"]["default_sha"],
                context["event"],
            )["status"]
            == "duplicate"
        )
    assert "unverified" in service.prs[1]["body"]


@pytest.mark.parametrize("mode", ["discover", "revise"])
@pytest.mark.parametrize("change", ["failed_check", "wrong_tree"])
def test_retry_rejects_failed_source_check_or_wrong_landed_tree(
    scenario,
    tmp_path,
    monkeypatch,
    mode,
    change,
):
    repo, service, api, _, _ = scenario
    context, artifact, sources = source_candidate(
        scenario,
        tmp_path,
        mode,
        incompatible=change == "failed_check",
    )
    interrupt_report(service, monkeypatch, mode)
    assert publish(api, repo, context, artifact)["status"] == "failed"
    landed = git(repo, "rev-parse", BRANCH)
    if change == "wrong_tree":
        message = git(repo, "show", "-s", "--format=%B", landed)
        base_tree = git(repo, "rev-parse", context["identity"]["head_sha"] + "^{tree}")
        landed = service.git(
            "commit-tree",
            base_tree,
            "-p",
            context["identity"]["head_sha"],
            content=message,
        ).stdout.strip()
        service.authors[landed] = BOT
        git(repo, "update-ref", "refs/heads/" + BRANCH, landed)
    service.requests.clear()
    rejected = publish(api, repo, context, artifact, sources=sources)
    assert rejected["status"] == "failed"
    if change == "failed_check":
        assert rejected["revalidation"]["groups"][0]["validation"]["status"] == "failed"
        assert rejected["revalidation"]["patch"] == ""
    else:
        assert "landed commit" in rejected["reason"]
    assert git(repo, "rev-parse", BRANCH) == landed
    assert not any(method != "GET" for method, _, _ in service.requests)
    assert not any(c["user"]["login"] == BOT for c in service.comments)


@pytest.mark.parametrize("change", ["command", "permission"])
def test_retry_rechecks_command_and_authority_after_commit_lands(
    scenario,
    tmp_path,
    monkeypatch,
    change,
):
    repo, service, api, _, _ = scenario
    context, artifact, sources = source_candidate(scenario, tmp_path, "revise")
    interrupt_report(service, monkeypatch, "revise")
    assert publish(api, repo, context, artifact)["status"] == "failed"
    landed = git(repo, "rev-parse", BRANCH)
    if change == "command":
        service.comments[0]["body"] += "\nChanged request."
    else:
        service.permission = "read"
    service.requests.clear()
    rejected = publish(api, repo, context, artifact, sources=sources)
    assert rejected["status"] == "deferred"
    assert git(repo, "rev-parse", BRANCH) == landed
    assert not any(method != "GET" for method, _, _ in service.requests)
    assert not any(c["user"]["login"] == BOT for c in service.comments)


def test_duplicate_command_uses_comment_id_and_digest_and_requires_new_comment(
    scenario,
):
    repo, service, api, _, _ = scenario
    initial(scenario)
    event, context, artifact = revision(scenario)
    assert publish(api, repo, context, artifact)["status"] == "published"
    before = git(repo, "rev-parse", BRANCH)
    assert (
        prepare_context(api, REPOSITORY, context["identity"]["default_sha"], event)[
            "status"
        ]
        == "duplicate"
    )
    assert publish(api, repo, context, artifact)["status"] == "duplicate"
    assert git(repo, "rev-parse", BRANCH) == before
    command = next(c for c in service.comments if c["id"] == event["comment"]["id"])
    command["body"] += "\nChanged request."
    event["comment"] = copy.deepcopy(command)
    assert (
        prepare_context(api, REPOSITORY, context["identity"]["default_sha"], event)[
            "status"
        ]
        == "deferred"
    )
    new_event = service.comment_event("/auto-sync\nReview the new evidence.")
    assert (
        prepare_context(api, REPOSITORY, context["identity"]["default_sha"], new_event)[
            "status"
        ]
        == "ready"
    )


def test_recheck_rejects_forged_ready_digest_and_preserves_failed_outcomes(scenario):
    repo, service, api, context, artifact = scenario
    forged = copy.deepcopy(artifact)
    forged["groups"][0]["patch"] = forged["groups"][0]["patch"].replace(
        "0.30.0",
        "0.99.0",
    )
    forged["patch"] = forged["groups"][0]["patch"]
    forged["patch_digest"] = hashlib.sha256(forged["patch"].encode()).hexdigest()
    forged["report_digest"] = report_digest(forged)
    result = publish(api, repo, context, forged)
    assert result["status"] == "failed"
    assert result["checked"] == forged
    assert result["revalidation"]["groups"][0]["status"] == "failed"
    assert not service.prs
    assert not any(method != "GET" for method, _, _ in service.requests)


@pytest.mark.parametrize("field", ["patch", "report_digest"])
def test_retry_rejects_fabricated_transport_before_remote_access(
    scenario,
    tmp_path,
    monkeypatch,
    field,
):
    repo, service, api, _, _ = scenario
    context, artifact, sources = source_candidate(scenario, tmp_path, "revise")
    interrupt_report(service, monkeypatch, "revise")
    assert publish(api, repo, context, artifact)["status"] == "failed"
    landed = git(repo, "rev-parse", BRANCH)
    forged = copy.deepcopy(artifact)
    forged[field] += "fabricated"
    service.requests.clear()
    rejected = publish(api, repo, context, forged, sources=sources)
    assert rejected["status"] == "failed"
    assert rejected["checked"] is None
    assert rejected["revalidation"] is None
    assert not service.requests
    assert git(repo, "rev-parse", BRANCH) == landed


def test_identity_is_frozen_from_context_and_not_artifact(scenario):
    repo, service, api, context, artifact = scenario
    artifact["identity"]["repository"] = "attacker/runner"
    artifact["report_digest"] = report_digest(artifact)
    result = publish(api, repo, context, artifact)
    assert result["status"] == "failed"
    assert not service.prs


def test_concurrent_discovery_claim_and_creation_keep_one_pr(scenario):
    repo, service, api, context, artifact = scenario
    service.before_pr_create = lambda: service.add_pr()
    result = publish(api, repo, context, artifact)
    assert result["status"] in {"published", "deferred"}
    assert len(service.prs) == 1
    assert len({pr["head"]["ref"] for pr in service.prs.values()}) == 1


def test_upstream_api_failure_is_failed_not_unchanged(scenario):
    _, service, api, context, _ = scenario
    service.fail_reads = True
    result = prepare_context(api, REPOSITORY, context["identity"]["default_sha"])
    assert result["status"] == "failed"


def test_empty_ready_patch_never_creates_pr_and_keeps_all_assessments(scenario):
    repo, service, api, context, _ = scenario
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    raw["identity"] = context["identity"]
    raw["groups"][0].update(
        status="blocked",
        patch="",
        reason="Missing required evidence.",
    )
    raw["candidates"][0]["status"] = "blocked"
    artifact = validate_candidate(repo, raw, context["identity"])
    result = publish(api, repo, context, artifact)
    assert result["status"] == "no_changes"
    assert len(result["checked"]["candidates"]) == 6
    assert not service.prs


@pytest.mark.parametrize("merged", [False, True])
def test_next_release_cycle_preserves_closed_branch_and_its_human_work(
    scenario,
    merged,
):
    repo, service, api, context, _ = scenario
    initial(scenario)
    human = service.human_commit("human.txt", "Keep the previous proposal branch.\n")
    service.prs[1]["state"] = "closed"
    default = context["identity"]["default_sha"]
    if merged:
        git(repo, "update-ref", "refs/heads/main", human)
        git(repo, "reset", "--hard", "main")
        default = human
    next_context = prepare_context(api, REPOSITORY, default)
    assert next_context["status"] == "ready"
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    raw["identity"] = next_context["identity"]
    group = raw["groups"][0]
    previous = "0.30.0" if merged else "0.29.0"
    group["rows"][0].update(
        old_engine_version=previous,
        engine_version="0.31.0",
        base_image="vllm/vllm-openai:v0.31.0",
    )
    group["patch"] = ""
    for path in ("pack/cuda/Dockerfile.vllm", "pack/matrix.yaml", SUPPORT):
        before = git(repo, "show", default + ":" + path) + "\n"
        if path == SUPPORT:
            after = before.replace(
                "<!-- runner-support-records:end -->",
                "| cuda | 13.0 | vllm | - | 0.31.0 | - | linux/amd64 | prepared |\n<!-- runner-support-records:end -->",
            )
        else:
            after = before.replace(previous, "0.31.0")
        group["patch"] += f"diff --git a/{path} b/{path}\n" + "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            ),
        )
    artifact = validate_candidate(repo, raw, next_context["identity"])
    assert artifact["patch"], artifact["groups"]
    result = publish(api, repo, next_context, artifact)
    assert result["status"] == "published", result
    assert len([p for p in service.prs.values() if p["state"] == "open"]) == 1
    assert service.prs[2]["head"]["ref"] != BRANCH
    assert git(repo, "rev-parse", BRANCH) == human
    assert (
        git(repo, "show", BRANCH + ":human.txt") == "Keep the previous proposal branch."
    )
    assert git(repo, "rev-parse", service.prs[2]["head"]["ref"] + "^") == default


def test_ambiguous_command_reports_blocked_without_waiting(scenario):
    _, service, api, context, _ = scenario
    initial(scenario)
    event = service.comment_event("/auto-sync")
    result = prepare_context(api, REPOSITORY, context["identity"]["default_sha"], event)
    assert result["status"] == "blocked"


def test_recovery_rejects_matching_metadata_on_wrong_source_tree(scenario):
    repo, service, api, context, artifact = scenario
    service.fail_after = "ref"
    assert publish(api, repo, context, artifact)["status"] == "failed"
    valid = git(repo, "rev-parse", BRANCH)
    message = git(repo, "show", "-s", "--format=%B", valid)
    base_tree = git(repo, "rev-parse", context["identity"]["head_sha"] + "^{tree}")
    wrong = service.git(
        "commit-tree",
        base_tree,
        "-p",
        context["identity"]["head_sha"],
        content=message,
    ).stdout.strip()
    service.authors[wrong] = BOT
    git(repo, "update-ref", "refs/heads/" + BRANCH, wrong)
    result = publish(api, repo, context, artifact)
    assert result["status"] == "failed"
    assert not service.prs
    assert git(repo, "rev-parse", BRANCH) == wrong


def test_publication_recheck_receives_independent_upstream_sources_and_pairs(
    scenario,
    monkeypatch,
):
    repo, _, api, context, artifact = scenario
    sources = {"vllm-project/vllm": repo}
    pairs = {
        "0.27.1rc1": {
            "engine_version": "0.27.1",
            "source": "https://github.com/vllm-project/vllm-ascend/releases/tag/v0.27.1rc1",
        },
    }
    original = publication.validate_candidate
    observed = []

    def observe(*args, **kwargs):
        observed.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(publication, "validate_candidate", observe)
    assert (
        publish(api, repo, context, artifact, sources=sources, ascend_pairs=pairs)[
            "status"
        ]
        == "published"
    )
    assert observed == [
        {
            "sources": sources,
            "ascend_pairs": pairs,
            "engine_prereleases": None,
            "prerelease_packages": None,
        },
    ]


@pytest.mark.parametrize("change", ["permission", "closed", "fork", "owner", "branch"])
def test_publication_rechecks_command_authority_and_pr_ownership(scenario, change):
    repo, service, api, _, _ = scenario
    initial(scenario)
    _, context, artifact = revision(scenario)
    before = git(repo, "rev-parse", BRANCH)
    if change == "permission":
        service.permission = "read"
    elif change == "closed":
        service.prs[1]["state"] = "closed"
    elif change == "fork":
        service.prs[1]["head"]["repo"]["full_name"] = "attacker/runner"
    elif change == "owner":
        service.prs[1]["user"]["login"] = "other-bot[bot]"
    else:
        service.prs[1]["head"]["ref"] = "human-branch"
    result = publish(api, repo, context, artifact)
    assert result["status"] == "deferred"
    assert git(repo, "rev-parse", BRANCH) == before
    assert result["checked"]["patch"] == artifact["patch"]


def test_incomplete_commit_history_fails_before_research(scenario, monkeypatch):
    _, service, api, context, _ = scenario
    initial(scenario)
    event = service.comment_event("/auto-sync\nUpdate the report.")
    original = api.pages

    def pages(path):
        return [{}] * 250 if path.endswith("/commits") else original(path)

    monkeypatch.setattr(api, "pages", pages)
    result = prepare_context(api, REPOSITORY, context["identity"]["default_sha"], event)
    assert result["status"] == "failed"
    assert "completeness" in result["reason"]


def test_local_publication_processes_receive_no_credentials(scenario, monkeypatch):
    repo, _, api, context, artifact = scenario
    monkeypatch.setenv("GH_TOKEN", "fake-write-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-write-secret")
    monkeypatch.setenv("AUTO_SYNC_MODEL_TOKEN", "fake-model-secret")
    original = subprocess.run
    observed = []

    def observe(*args, **kwargs):
        env = kwargs.get("env")
        if env is not None and "GIT_INDEX_FILE" not in env:
            observed.append(env)
            assert "fake-" not in json.dumps(env)
            assert not kwargs.get("shell", False)
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", observe)
    assert publish(api, repo, context, artifact)["status"] == "published"
    assert observed


def test_human_report_edit_cannot_hide_a_pending_managed_pr(scenario):
    _, service, api, context, _ = scenario
    initial(scenario)
    service.prs[1]["body"] = "Maintainer edited the proposal report."
    result = prepare_context(api, REPOSITORY, context["identity"]["default_sha"])
    assert result["status"] == "deferred"


def test_discovery_preserves_unclaimed_branch_with_nullable_author(scenario):
    repo, service, api, context, artifact = scenario
    initial(scenario)
    human = service.human_commit("human.txt", "Keep this unclaimed branch.\n")
    service.authors[human] = None
    service.prs.clear()
    result = publish(api, repo, context, artifact)
    assert result["status"] == "deferred"
    assert git(repo, "rev-parse", BRANCH) == human
    assert not service.prs


def test_publication_revalidates_exact_prerelease_permission(scenario):
    repo, _, api, _, _ = scenario
    initial(scenario)
    _event, context, _ = revision(scenario, "/auto-sync\nUse vLLM 0.31.0rc1 for CUDA.")
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    raw["identity"] = context["identity"]
    row = raw["groups"][0]["rows"][0]
    row.update(
        old_engine_version="0.30.0",
        engine_version="0.31.0rc1",
        base_image="vllm/vllm-openai:v0.31.0rc1",
    )
    patches = []
    for path in ("pack/cuda/Dockerfile.vllm", "pack/matrix.yaml", SUPPORT):
        old = git(repo, "show", context["identity"]["head_sha"] + ":" + path) + "\n"
        if path == SUPPORT:
            new = old.replace(
                "<!-- runner-support-records:end -->",
                "| cuda | 13.0 | vllm | - | 0.31.0rc1 | - | linux/amd64 | prepared |\n<!-- runner-support-records:end -->",
            )
        else:
            new = old.replace("0.30.0", "0.31.0rc1")
        patches.append(
            f"diff --git a/{path} b/{path}\n"
            + "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile="a/" + path,
                    tofile="b/" + path,
                ),
            ),
        )
    raw["groups"][0]["patch"] = "".join(patches)
    permission = {("cuda", "vllm", "0.31.0rc1")}
    checked = validate_candidate(
        repo,
        raw,
        raw["identity"],
        engine_prereleases=permission,
    )
    assert checked["patch"]
    head = git(repo, "rev-parse", context["branch"])
    rejected = publish(api, repo, context, checked)
    assert rejected["status"] == "failed"
    assert git(repo, "rev-parse", context["branch"]) == head
    accepted = publish(api, repo, context, checked, engine_prereleases=permission)
    assert accepted["status"] == "published"
    assert git(repo, "rev-parse", context["branch"] + "^") == head
