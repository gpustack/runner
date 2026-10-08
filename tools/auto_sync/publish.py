"""Clean-runner publication and durable single-proposal control."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import requests

from tools.auto_sync.checks import _clone, _git, validate_candidate, verify_artifact
from tools.auto_sync.proposal import (
    ProposalError,
    load_json,
    require,
    validate_identity,
)

BRANCH = "auto-sync/runner-upgrades"
MARKER = "<!-- runner-auto-sync: "
COMMIT_MARKER = "Runner-Auto-Sync: "


class GitHubError(ValueError):
    def __init__(self, method, path, status):
        self.status = status
        super().__init__(f"GitHub {method} {path.split('?')[0]} failed ({status}).")


class GitHub:
    """Bounded REST access; only the clean publication job gets a write token."""

    def __init__(self, token, bot_login, *, api_url="https://api.github.com"):
        require(isinstance(token, str) and bool(token.strip()), "missing GitHub token")
        require(
            isinstance(bot_login, str) and bot_login.endswith("[bot]"),
            "missing trusted App bot login",
        )
        parsed = urlsplit(api_url)
        require(
            parsed.scheme == "https"
            or (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost"}
            ),
            "GitHub API requires HTTPS outside local fixtures",
        )
        self.bot_login = bot_login
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )

    def request(self, method, path, body=None):
        require(
            path.startswith("/") and not path.startswith("//"),
            "invalid GitHub API path",
        )
        try:
            response = self.session.request(
                method,
                self.api_url + path,
                json=body,
                timeout=(10, 300),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise GitHubError(method, path, "transport") from None
        if not 200 <= response.status_code < 300:
            raise GitHubError(method, path, response.status_code)
        return load_json(response.text)

    def pages(self, path):
        records = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 21):
            batch = self.request(
                "GET",
                path + separator + urlencode({"per_page": 100, "page": page}),
            )
            require(isinstance(batch, list), "invalid GitHub list response")
            records.extend(batch)
            if len(batch) < 100:
                return records
        msg = "GitHub pagination exceeded the bounded context limit."
        raise ProposalError(msg)


def _root(repository):
    return "/repos/" + repository


def _marker(data):
    return MARKER + json.dumps(data, sort_keys=True, separators=(",", ":")) + " -->"


def _record(text, prefix=MARKER):
    lines = (text or "").splitlines()
    line = lines[2:3] if prefix == COMMIT_MARKER else lines[:1]
    if not line or not line[0].startswith(prefix):
        return None
    value = line[0][len(prefix) :]
    if prefix == MARKER:
        if not value.endswith(" -->"):
            return None
        value = value[:-4]
    try:
        record = load_json(value)
    except ProposalError:
        return None
    return record if isinstance(record, dict) else None


def _managed(pr, github, repository):
    record = _record(pr.get("body"))
    branch = pr.get("head", {}).get("ref", "")
    namespace = branch == BRANCH or re.fullmatch(
        re.escape(BRANCH) + r"-after-[1-9][0-9]*",
        branch,
    )
    return (
        pr.get("user", {}).get("login") == github.bot_login
        and (record == {"kind": "proposal", "repository": repository} or namespace)
        and pr.get("base", {}).get("repo", {}).get("full_name") == repository
    )


def _open(github, repository):
    return [
        p
        for p in github.pages(_root(repository) + "/pulls?state=open")
        if _managed(p, github, repository)
    ]


def _discovery_branch(github, repository):
    closed = [
        p["number"]
        for p in github.pages(_root(repository) + "/pulls?state=closed")
        if _managed(p, github, repository)
    ]
    # Keep closed branches intact. Concurrent runs choose the same next branch.
    return BRANCH + "-after-" + str(max(closed)) if closed else BRANCH


def _owned(pr, github, repository, default_branch):
    return (
        _managed(pr, github, repository)
        and pr.get("state") == "open"
        and pr.get("head", {}).get("repo", {}).get("full_name") == repository
        and isinstance(pr.get("head", {}).get("ref"), str)
        and bool(pr["head"]["ref"])
        and pr.get("base", {}).get("ref") == default_branch
    )


def _command(github, repository, event):
    if (
        not isinstance(event, dict)
        or event.get("action") != "created"
        or event.get("repository", {}).get("full_name") != repository
        or "pull_request" not in event.get("issue", {})
    ):
        return {
            "status": "ignored",
            "reason": "Only newly created PR Conversation commands are accepted.",
        }
    comment_id = event.get("comment", {}).get("id")
    number = event["issue"].get("number")
    require(
        type(comment_id) is int
        and comment_id > 0
        and type(number) is int
        and number > 0,
        "invalid command event identity",
    )
    comment = github.request(
        "GET",
        _root(repository) + f"/issues/comments/{comment_id}",
    )
    body = comment.get("body", "")
    if (
        comment.get("id") != comment_id
        or body != event["comment"].get("body")
        or comment.get("user") != event["comment"].get("user")
        or comment.get("issue_url")
        != github.api_url + _root(repository) + f"/issues/{number}"
    ):
        return {
            "status": "deferred",
            "reason": "Command identity or content changed; create a new comment.",
        }
    lines = body.strip().splitlines()
    if (
        not lines
        or lines[0].strip() != "/auto-sync"
        or comment.get("user", {}).get("type") != "User"
    ):
        return {"status": "ignored", "reason": "Not a maintainer auto-sync command."}
    login = comment["user"]["login"]
    permission = github.request(
        "GET",
        _root(repository) + "/collaborators/" + quote(login, safe="") + "/permission",
    )
    if permission.get("permission") not in {"admin", "maintain", "write"}:
        return {
            "status": "ignored",
            "reason": "Command author lacks repository write permission.",
        }
    if not "\n".join(lines[1:]).strip():
        return {"status": "blocked", "reason": "Command has no requested revision."}
    return {
        "status": "ready",
        "comment": comment,
        "number": number,
        "digest": hashlib.sha256(body.encode()).hexdigest(),
    }


def _history(github, repository, number):
    root = _root(repository)
    comments = github.pages(root + f"/issues/{number}/comments")
    commits = github.pages(root + f"/pulls/{number}/commits")
    require(len(commits) < 250, "PR commit history reached GitHub's completeness limit")
    records = []
    for comment in comments:
        if comment.get("user", {}).get("login") == github.bot_login:
            record = _record(comment.get("body"))
            if record and record.get("kind") == "result":
                records.append(record)
    for commit in commits:
        if (commit.get("author") or {}).get("login") == github.bot_login:
            record = _record(commit.get("commit", {}).get("message"), COMMIT_MARKER)
            if record and record.get("kind") == "result":
                records.append(dict(record, commit_sha=commit["sha"]))
    return comments, commits, records


def _processed(records, identity):
    return [
        r
        for r in records
        if r.get("identity", {}).get("repository") == identity["repository"]
        and r.get("identity", {}).get("pr_number") == identity["pr_number"]
        and r.get("identity", {}).get("command_id") == identity["command_id"]
    ]


def prepare_context(github, repository, default_sha, event=None):
    """
    Freeze trusted event/default/head identities before research or model startup.

    The returned revision context includes current reports, diff, reviews,
    comments, commits, recipes, and the release guide. Treat their contents as
    data, never shell commands. Pass this context unchanged between jobs.
    """
    try:
        identity = {
            "repository": repository,
            "default_sha": default_sha,
            "head_sha": default_sha,
            "mode": "discover",
            "pr_number": None,
            "command_id": None,
            "command_digest": None,
        }
        validate_identity(identity)
        root = _root(repository)
        metadata = github.request("GET", root)
        default_branch = metadata["default_branch"]
        if event is None:
            pending = _open(github, repository)
            return {
                "status": "deferred" if pending else "ready",
                "reason": "An auto-sync proposal remains open."
                if pending
                else "No pending auto-sync proposal.",
                "identity": identity,
                "default_branch": default_branch,
                "pending": pending,
                "branch": _discovery_branch(github, repository)
                if not pending
                else None,
            }
        command = _command(github, repository, event)
        if command["status"] != "ready":
            return command
        number = command["number"]
        pr = github.request("GET", root + f"/pulls/{number}")
        if not _owned(pr, github, repository, default_branch):
            return {
                "status": "deferred",
                "reason": "PR is not an open repository-owned auto-sync proposal.",
            }
        identity.update(
            mode="revise",
            pr_number=number,
            head_sha=pr["head"]["sha"],
            command_id=command["comment"]["id"],
            command_digest=command["digest"],
        )
        validate_identity(identity)
        comments, commits, records = _history(github, repository, number)
        seen = _processed(records, identity)
        if seen:
            same = all(
                r["identity"].get("command_digest") == command["digest"] for r in seen
            )
            return {
                "status": "duplicate" if same else "deferred",
                "reason": "Command already processed."
                if same
                else "Processed command was edited; create a new comment.",
                "identity": identity,
                "default_branch": default_branch,
                "records": seen,
            }
        diff = github.pages(root + f"/pulls/{number}/files")
        constraints = {}
        paths = {
            item["filename"]
            for item in diff
            if item["filename"].startswith("pack/")
            and "/Dockerfile." in item["filename"]
        }
        paths.add("docs/release-automation.md")
        paths.add("pack/matrix.yaml")
        for path in sorted(paths):
            try:
                file = github.request(
                    "GET",
                    root
                    + "/contents/"
                    + quote(path, safe="/")
                    + "?"
                    + urlencode({"ref": identity["head_sha"]}),
                )
            except GitHubError as exc:
                if exc.status == 404 and path == "docs/release-automation.md":
                    continue
                raise
            require(
                file.get("encoding") == "base64",
                "invalid constraint file encoding",
            )
            constraints[path] = base64.b64decode(file["content"]).decode()
        # The mutable head must still equal the revision used for all reads.
        latest = github.request("GET", root + f"/pulls/{number}")
        if (
            not _owned(latest, github, repository, default_branch)
            or latest["head"]["sha"] != identity["head_sha"]
        ):
            return {
                "status": "deferred",
                "reason": "PR head changed while restoring context.",
                "identity": identity,
                "default_branch": default_branch,
            }
        return {
            "status": "ready",
            "reason": "Authorized focused revision.",
            "identity": identity,
            "default_branch": default_branch,
            "branch": pr["head"]["ref"],
            "event": event,
            "pr": pr,
            "command": command["comment"],
            "comments": comments,
            "commits": commits,
            "diff": diff,
            "reviews": github.pages(root + f"/pulls/{number}/reviews"),
            "review_comments": github.pages(root + f"/pulls/{number}/comments"),
            "constraints": constraints,
            "instructions": "Apply only the requested revision and necessary compatibility changes. Preserve accepted versions, unaffected changes, direct human commits, and lasting pins. Explain any necessary scope expansion. Report ambiguous or conflicting requests as blocked.",
        }
    except (GitHubError, ProposalError, KeyError, TypeError, ValueError) as exc:
        return {"status": "failed", "reason": str(exc)}


def _result(status, reason, checked=None, **fields):
    return {"status": status, "reason": reason, "checked": checked, **fields}


def _ref(github, repository, branch):
    try:
        return github.request(
            "GET",
            _root(repository) + "/git/ref/heads/" + quote(branch, safe="/"),
        )["object"]["sha"]
    except GitHubError as exc:
        if exc.status == 404:
            return None
        raise


def _publication_record(checked):
    return {
        "kind": "result",
        "identity": checked["identity"],
        "patch_digest": checked["patch_digest"],
        "report_digest": checked["report_digest"],
    }


def _same_publication(record, checked):
    expected = _publication_record(checked)
    return all(record.get(key) == value for key, value in expected.items())


def _render_report(checked, commit_sha=None):
    lines = [
        "Runner upgrade proposal",
        "",
        "Configuration is proposed for human review. Image builds, measured dependencies, and GPU execution remain unverified.",
        "Run Pack after merge for the accepted combinations.",
        "",
    ]
    if commit_sha:
        lines += [f"Commit: `{commit_sha}`", ""]
    lines += ["Candidate outcomes", ""]
    for candidate in checked["candidates"]:
        lines.append(
            f"- {candidate['subscription']}: {candidate['status']}. {candidate['reason']}",
        )
    for group in checked["groups"]:
        lines += [
            "",
            f"Group {group['id']}: {group['status']}",
            "",
            group["reason"],
            "",
            group["report"],
            "",
        ]
        for row in group["rows"]:
            lines += [
                f"- {row['backend']}/{row['service']}, variant `{row['variant'] or '-'}`, runtime `{row['runtime']}`, platform `{row['platform']}`: `{row['old_engine_version']}` to `{row['engine_version']}`; plugin `{row['plugin_version']}`. Evidence: {row['conclusion']}.",
            ]
        # Exact row data retains images, digests, packages, patches, sources,
        # executed checks and deferred work without guessing unknown values.
        rows = {"rows": group["rows"], "validation": group["validation"]}
        lines += ["", "```json", json.dumps(rows, indent=2, ensure_ascii=True), "```"]
    return "\n".join(lines)


def _prepare_tree(repo, checked):
    identity = checked["identity"]
    with tempfile.TemporaryDirectory(prefix="runner-publish-") as temporary:
        scratch = Path(temporary)
        home = scratch / "home"
        home.mkdir()
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home),
            "TMPDIR": str(scratch),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/usr/bin/false",
            "SSH_ASKPASS": "/usr/bin/false",
        }
        work = scratch / "work"
        _clone(repo, identity["head_sha"], work, env)
        _git(
            env,
            work,
            "apply",
            "--check",
            "--whitespace=error",
            "-",
            text=checked["patch"],
        )
        _git(env, work, "apply", "--whitespace=error", "-", text=checked["patch"])
        _git(env, work, "add", "-A")
        paths = list(
            filter(
                None,
                _git(env, work, "diff", "--cached", "--name-only", "-z").split("\0"),
            ),
        )
        require(bool(paths), "accepted patch has no source changes")
        entries = []
        for path in paths:
            staged = _git(env, work, "ls-files", "--stage", "--", path)
            content = None
            if staged:
                require(
                    staged.startswith("100644 "),
                    "publication requires regular text files",
                )
                content = _git(env, work, "show", ":" + path)
            entries.append({"path": path, "content": content})
        return (
            _git(env, work, "write-tree").strip(),
            _git(env, work, "rev-parse", identity["head_sha"] + "^{tree}").strip(),
            entries,
        )


def _upload_commit(github, repo, checked):
    identity = checked["identity"]
    root = _root(identity["repository"])
    expected_tree, base_tree, files = _prepare_tree(repo, checked)
    entries = []
    for file in files:
        sha = None
        if file["content"] is not None:
            sha = github.request(
                "POST",
                root + "/git/blobs",
                {
                    "encoding": "base64",
                    "content": base64.b64encode(file["content"].encode()).decode(),
                },
            )["sha"]
        entries.append(
            {"path": file["path"], "mode": "100644", "type": "blob", "sha": sha},
        )
    tree = github.request(
        "POST",
        root + "/git/trees",
        {"base_tree": base_tree, "tree": entries},
    )["sha"]
    require(
        tree == expected_tree,
        "published tree differs from the clean accepted patch",
    )
    bot = github.request("GET", "/users/" + quote(github.bot_login, safe=""))
    require(
        bot["login"] == github.bot_login and type(bot["id"]) is int,
        "GitHub App identity differs",
    )
    author = {
        "name": github.bot_login,
        "email": f"{bot['id']}+{github.bot_login}@users.noreply.github.com",
    }
    record = json.dumps(
        _publication_record(checked),
        sort_keys=True,
        separators=(",", ":"),
    )
    message = (
        "chore: update runner proposal\n\n"
        + COMMIT_MARKER
        + record
        + "\n\n"
        + _render_report(checked)
        + f"\n\nSigned-off-by: {author['name']} <{author['email']}>\n"
    )
    return github.request(
        "POST",
        root + "/git/commits",
        {
            "tree": tree,
            "parents": [identity["head_sha"]],
            "message": message,
            "author": author,
            "committer": author,
        },
    )["sha"]


def _check_landed(github, repo, checked, sha):
    require(isinstance(sha, str), "published command lacks a commit reference")
    commit = github.request(
        "GET",
        _root(checked["identity"]["repository"]) + "/git/commits/" + sha,
    )
    expected_tree, _, _ = _prepare_tree(repo, checked)
    require(
        [p["sha"] for p in commit["parents"]] == [checked["identity"]["head_sha"]]
        and commit["tree"]["sha"] == expected_tree,
        "landed commit differs from the clean accepted patch or parent",
    )


def _fresh_revision(github, context):
    identity = context["identity"]
    repository = identity["repository"]
    command = _command(github, repository, context["event"])
    if (
        command["status"] != "ready"
        or command["digest"] != identity["command_digest"]
        or command["number"] != identity["pr_number"]
        or command["comment"]["id"] != identity["command_id"]
    ):
        return None, [], "Command identity or authorization changed."
    pr = github.request("GET", _root(repository) + f"/pulls/{identity['pr_number']}")
    if (
        not _owned(pr, github, repository, context["default_branch"])
        or pr["head"]["ref"] != context["branch"]
    ):
        return None, [], "PR ownership or open state changed."
    _, _, records = _history(github, repository, identity["pr_number"])
    return pr, _processed(records, identity), None


def _report_revision(github, pr, checked, commit_sha):
    root = _root(checked["identity"]["repository"])
    number = pr["number"]
    record = dict(_publication_record(checked), commit_sha=commit_sha)
    marker = _marker(record)
    body = (
        marker
        + "\n\nAddressed items and unresolved outcomes\n\n"
        + _render_report(checked, commit_sha)
    )
    # Both PR history and commit metadata are durable, independent of caches.
    comments = github.pages(root + f"/issues/{number}/comments")
    replied = any(
        c.get("user", {}).get("login") == github.bot_login
        and _record(c.get("body")) == record
        for c in comments
    )
    latest = github.request("GET", root + f"/pulls/{number}")
    current_body = latest.get("body") or ""
    if marker not in current_body:
        github.request(
            "PATCH",
            root + f"/pulls/{number}",
            {"body": current_body + "\n\n" + body},
        )
    if not replied:
        github.request("POST", root + f"/issues/{number}/comments", {"body": body})


def _revise(github, repo, context, checked):
    identity = context["identity"]
    pr, seen, reason = _fresh_revision(github, context)
    if reason:
        return _result("deferred", reason, checked)
    if seen:
        if not all(_same_publication(r, checked) for r in seen):
            return _result(
                "deferred",
                "Command already processed with different content or output; create a new comment.",
                checked,
            )
        commit_sha = next(
            (r.get("commit_sha") for r in seen if r.get("commit_sha")),
            None,
        )
        if checked["patch"]:
            _check_landed(github, repo, checked, commit_sha)
        _report_revision(github, pr, checked, commit_sha)
        return _result(
            "duplicate",
            "Adopted an already published command.",
            checked,
            pr_number=pr["number"],
            commit_sha=commit_sha,
        )
    if pr["head"]["sha"] != identity["head_sha"]:
        return _result("deferred", "PR head changed; recompute the revision.", checked)
    if not checked["patch"]:
        _report_revision(github, pr, checked, None)
        return _result(
            "no_changes",
            "No accepted source changes; outcomes were reported.",
            checked,
            pr_number=pr["number"],
        )
    commit_sha = _upload_commit(github, repo, checked)
    latest, seen, reason = _fresh_revision(github, context)
    if reason or seen or latest["head"]["sha"] != identity["head_sha"]:
        return _result(
            "deferred",
            reason or "PR head or command state changed before publication.",
            checked,
        )
    try:
        github.request(
            "PATCH",
            _root(identity["repository"])
            + "/git/refs/heads/"
            + quote(context["branch"], safe="/"),
            {"sha": commit_sha, "force": False},
        )
    except GitHubError as exc:
        if exc.status in {409, 422}:
            return _result(
                "deferred",
                "Fast-forward publication rejected a concurrent branch change.",
                checked,
            )
        raise
    _report_revision(github, latest, checked, commit_sha)
    return _result(
        "published",
        "Appended the authorized revision.",
        checked,
        pr_number=latest["number"],
        commit_sha=commit_sha,
    )


def _branch_record(github, repository, sha):
    commit = github.request("GET", _root(repository) + "/commits/" + sha)
    if (commit.get("author") or {}).get("login") != github.bot_login:
        return None
    return _record(commit.get("commit", {}).get("message"), COMMIT_MARKER)


def _discover(github, repo, context, checked):
    identity = context["identity"]
    repository = identity["repository"]
    root = _root(repository)
    pending = _open(github, repository)
    if pending:
        return _result(
            "deferred",
            "An auto-sync proposal remains open; keep newer findings in the job summary.",
            checked,
            pr_number=pending[0]["number"],
        )
    if not checked["patch"]:
        return _result(
            "no_changes",
            "No accepted source changes; no PR was created.",
            checked,
        )
    current_default = github.request(
        "GET",
        root + "/git/ref/heads/" + quote(context["default_branch"], safe="/"),
    )["object"]["sha"]
    if current_default != identity["default_sha"]:
        return _result(
            "deferred",
            "Default branch changed; recompute discovery.",
            checked,
        )
    branch = _discovery_branch(github, repository)
    if branch != context["branch"]:
        return _result(
            "deferred",
            "Proposal cycle changed; recompute discovery.",
            checked,
        )
    current = _ref(github, repository, branch)
    record = _branch_record(github, repository, current) if current else None
    recovered = record is not None and _same_publication(record, checked)
    if recovered:
        _check_landed(github, repo, checked, current)
    if (
        record
        and not recovered
        and record.get("identity", {}).get("default_sha") == identity["default_sha"]
    ):
        return _result(
            "deferred",
            "Another proposal already claimed the stable branch.",
            checked,
        )
    commit_sha = current if recovered else _upload_commit(github, repo, checked)
    if not recovered:
        if _open(github, repository):
            return _result(
                "deferred",
                "A concurrent discovery created a proposal.",
                checked,
            )
        try:
            if current is None:
                github.request(
                    "POST",
                    root + "/git/refs",
                    {"ref": "refs/heads/" + branch, "sha": commit_sha},
                )
            else:
                github.request(
                    "PATCH",
                    root + "/git/refs/heads/" + quote(branch, safe="/"),
                    {"sha": commit_sha, "force": False},
                )
        except GitHubError as exc:
            if exc.status not in {409, 422}:
                raise
            landed = _ref(github, repository, branch)
            record = _branch_record(github, repository, landed) if landed else None
            if record is None or not _same_publication(record, checked):
                return _result(
                    "deferred",
                    "A concurrent branch claim prevents stale publication.",
                    checked,
                )
            _check_landed(github, repo, checked, landed)
            commit_sha = landed
    # Recheck immediately before creation; the stable branch also makes a
    # concurrent identical-head PR creation reject instead of duplicating.
    pending = _open(github, repository)
    if pending:
        return _result(
            "deferred",
            "A managed proposal already exists.",
            checked,
            pr_number=pending[0]["number"],
        )
    if _ref(github, repository, branch) != commit_sha:
        return _result(
            "deferred",
            "Proposal branch changed before PR creation.",
            checked,
        )
    body = (
        _marker({"kind": "proposal", "repository": repository})
        + "\n\n"
        + _render_report(checked, commit_sha)
    )
    try:
        pr = github.request(
            "POST",
            root + "/pulls",
            {
                "head": branch,
                "base": context["default_branch"],
                "title": "chore: update runner dependencies",
                "body": body,
                "draft": False,
            },
        )
    except GitHubError as exc:
        if exc.status not in {409, 422}:
            raise
        pending = _open(github, repository)
        if not pending:
            raise
        return _result(
            "deferred",
            "A concurrent discovery created the managed PR.",
            checked,
            pr_number=pending[0]["number"],
        )
    return _result(
        "published",
        "Created one formal upgrade proposal.",
        checked,
        pr_number=pr["number"],
        commit_sha=commit_sha,
    )


def publish(github, repo, context, artifact, *, sources=None, ascend_pairs=None):
    """
    Recheck an artifact with trusted code and publish only its accepted patch.

    ``repo`` supplies clean local objects for the frozen default and head. The
    controller supplies upstream ``sources`` and ``ascend_pairs`` independently
    of agent output. Results retain the full checked outcomes on no-write paths.
    A failed mutation is not retried blindly; a later call adopts landed state.
    """
    checked = None
    try:
        identity = context["identity"]
        validate_identity(identity)
        raw = verify_artifact(artifact, identity)
        checked = validate_candidate(
            Path(repo),
            raw,
            identity,
            sources=sources,
            ascend_pairs=ascend_pairs,
        )
        if context["status"] != "ready":
            return _result(context["status"], context["reason"], checked)
        if identity["mode"] == "revise":
            return _revise(github, repo, context, checked)
        return _discover(github, repo, context, checked)
    except (
        GitHubError,
        ProposalError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _result("failed", str(exc), checked)
