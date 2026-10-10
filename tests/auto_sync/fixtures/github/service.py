"""Stateful GitHub REST fixture backed by disposable, real Git objects."""

import base64
import copy
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


class PlainText(str):
    """Marker for a response body served as plain text instead of JSON."""

    __slots__ = ()


class FakeGitHub:
    def __init__(self, repo, repository, bot):
        self.repo = repo
        self.repository = repository
        self.bot = bot
        self.prs = {}
        self.comments = []
        self.reviews = []
        self.inline = []
        self.requests = []
        self.permission = "write"
        self.fail_reads = False
        self.fail_after = None
        self.before_pr_create = None
        self.before_ref_update = None
        self.blobs = {}
        self.trees = {}
        self.authors = {}
        self.pending_pr = None
        self.actions_runs = {}

    def git(self, *args, content=None, env=None, check=True):
        return subprocess.run(  # noqa: S603 - controlled fixture Git operations.
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(self.repo), *args],  # noqa: S607 - fixture only.
            input=content,
            env=env,
            check=check,
            capture_output=True,
            text=True,
        )

    def sha(self, ref):
        result = self.git("rev-parse", "--verify", ref, check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def __enter__(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond("GET")

            def do_POST(self):
                self.respond("POST")

            def do_PATCH(self):
                self.respond("PATCH")

            def respond(self, method):
                body = None
                if self.headers.get("Content-Length"):
                    body = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"])),
                    )
                fixture.requests.append((method, self.path, copy.deepcopy(body)))
                status, result = fixture.request(method, self.path, body)
                if isinstance(result, PlainText):
                    data = result.encode()
                    content_type = "text/plain; charset=utf-8"
                else:
                    data = json.dumps(result).encode()
                    content_type = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def add_pr(self):
        body = self.pending_pr
        number = len(self.prs) + 1
        pr = {
            "number": number,
            "state": "open",
            "draft": body["draft"],
            "title": body["title"],
            "body": body["body"],
            "user": {"login": self.bot, "type": "Bot"},
            "base": {"ref": body["base"], "repo": {"full_name": self.repository}},
            "head": {
                "ref": body["head"],
                "sha": self.sha(body["head"]),
                "repo": {"full_name": self.repository},
            },
        }
        self.prs[number] = pr
        return pr

    def current_pr(self, number):
        pr = self.prs[number]
        sha = self.sha(pr["head"]["ref"])
        if sha is not None:
            pr["head"]["sha"] = sha
        return copy.deepcopy(pr)

    def comment_event(self, body):
        number = 1
        comment = {
            "id": len(self.comments) + 100,
            "body": body,
            "user": {"login": "maintainer", "type": "User"},
            "issue_url": f"{self.url}/repos/{self.repository}/issues/{number}",
        }
        self.comments.append(comment)
        return {
            "action": "created",
            "repository": {"full_name": self.repository},
            "issue": {"number": number, "pull_request": {}},
            "comment": copy.deepcopy(comment),
        }

    def human_commit(self, path, content):
        branch = self.prs[1]["head"]["ref"]
        old = self.sha(branch)
        current = self.git("rev-parse", old + "^{tree}").stdout.strip()
        blob = self.git("hash-object", "-w", "--stdin", content=content).stdout.strip()
        tree = self.make_tree(
            current,
            [{"path": path, "mode": "100644", "type": "blob", "sha": blob}],
        )
        new = self.git(
            "commit-tree",
            tree,
            "-p",
            old,
            content="Human edit\n",
        ).stdout.strip()
        self.git("update-ref", "refs/heads/" + branch, new)
        self.authors[new] = "maintainer"
        return new

    def make_tree(self, base, entries):
        index = self.repo.parent / "fixture-index"
        index.unlink(missing_ok=True)
        env = dict(os.environ, GIT_INDEX_FILE=str(index))
        self.git("read-tree", base, env=env)
        for item in entries:
            if item["sha"] is None:
                self.git("update-index", "--force-remove", "--", item["path"], env=env)
            else:
                self.git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    item["mode"],
                    item["sha"],
                    item["path"],
                    env=env,
                )
        return self.git("write-tree", env=env).stdout.strip()

    def commit(self, sha):
        return {
            "sha": sha,
            "tree": {"sha": self.git("rev-parse", sha + "^{tree}").stdout.strip()},
            "message": self.git("show", "-s", "--format=%B", sha).stdout.strip(),
            "parents": [
                {"sha": p}
                for p in self.git("show", "-s", "--format=%P", sha).stdout.split()
            ],
            "author": {
                "name": self.bot,
                "email": "123+runner-sync[bot]@users.noreply.github.com",
            },
        }

    def commit_list(self, pr):
        shas = self.git(
            "rev-list",
            "--reverse",
            "main.." + pr["head"]["sha"],
        ).stdout.split()
        return [
            {
                "sha": sha,
                "commit": {"message": self.commit(sha)["message"]},
                "author": (
                    None
                    if self.authors.get(sha, self.bot) is None
                    else {"login": self.authors.get(sha, self.bot)}
                ),
            }
            for sha in shas
        ]

    def files(self, base, head):
        names = self.git("diff", "--name-only", base, head).stdout.splitlines()
        return [
            {"filename": name, "patch": self.git("diff", base, head, "--", name).stdout}
            for name in names
        ]

    def failure(self, point):
        if self.fail_after == point:
            self.fail_after = None
            return 500, {"message": "Injected interruption after server-side mutation."}
        return None

    def request(self, method, url, body):  # noqa: PLR0911 - one response per simulated REST route.
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        prefix = "/repos/" + self.repository
        if path == "/users/" + self.bot:
            return 200, {"login": self.bot, "id": 123}
        if not path.startswith(prefix):
            return 404, {}
        route = path[len(prefix) :]
        if self.fail_reads and method == "GET":
            return 503, {}
        if method == "GET":
            if route == "":
                return 200, {"full_name": self.repository, "default_branch": "main"}
            if route.startswith("/actions/runs/"):
                parts = route.split("/")
                record = self.actions_runs.get(parts[3])
                if record is None:
                    return 404, {}
                if len(parts) == 5 and parts[4] == "jobs":
                    jobs = record.get("jobs", [])
                    return 200, {"total_count": len(jobs), "jobs": jobs}
                return 200, record.get("run", {})
            if route.startswith("/actions/jobs/") and route.endswith("/logs"):
                job_id = route.split("/")[3]
                for record in self.actions_runs.values():
                    if job_id in record.get("logs", {}):
                        return 200, PlainText(record["logs"][job_id])
                return 404, PlainText("")
            if route == "/pulls":
                state = query.get("state", ["open"])[0]
                return self.page(
                    [
                        self.current_pr(n)
                        for n, p in self.prs.items()
                        if p["state"] == state
                    ],
                    query,
                )
            if route.startswith("/collaborators/"):
                return 200, {"permission": self.permission}
            if route.startswith("/git/ref/heads/"):
                sha = self.sha("refs/heads/" + route[len("/git/ref/heads/") :])
                return (200, {"object": {"sha": sha}}) if sha else (404, {})
            if route.startswith("/git/commits/"):
                return 200, self.commit(route.rsplit("/", 1)[-1])
            if route.startswith("/commits/"):
                sha = route.rsplit("/", 1)[-1]
                return 200, {
                    "sha": sha,
                    "commit": {"message": self.commit(sha)["message"]},
                    "author": (
                        None
                        if self.authors.get(sha, self.bot) is None
                        else {"login": self.authors.get(sha, self.bot)}
                    ),
                }
            if route.startswith("/contents/"):
                name = route[len("/contents/") :]
                sha = query["ref"][0]
                result = self.git("show", sha + ":" + name, check=False)
                return (
                    (
                        200,
                        {
                            "encoding": "base64",
                            "content": base64.b64encode(
                                result.stdout.encode(),
                            ).decode(),
                        },
                    )
                    if result.returncode == 0
                    else (404, {})
                )
            if route.startswith("/issues/comments/"):
                return 200, next(
                    c for c in self.comments if c["id"] == int(route.rsplit("/", 1)[-1])
                )
            if route.startswith("/issues/"):
                return self.page(self.comments, query)
            if route.startswith("/pulls/"):
                parts = route.split("/")
                pr = self.current_pr(int(parts[2]))
                if len(parts) == 3:
                    return 200, pr
                records = {
                    "reviews": self.reviews,
                    "comments": self.inline,
                    "commits": self.commit_list(pr),
                    "files": self.files(self.sha("main"), pr["head"]["sha"]),
                }
                return self.page(records[parts[3]], query)
        if method == "POST":
            if route == "/git/blobs":
                content = base64.b64decode(body["content"]).decode()
                sha = self.git(
                    "hash-object",
                    "-w",
                    "--stdin",
                    content=content,
                ).stdout.strip()
                self.blobs[sha] = content
                return 201, {"sha": sha}
            if route == "/git/trees":
                tree = self.make_tree(body["base_tree"], body["tree"])
                self.trees[tree] = body["tree"]
                return 201, {"sha": tree}
            if route == "/git/commits":
                args = ["commit-tree", body["tree"]]
                for parent in body["parents"]:
                    args += ["-p", parent]
                sha = self.git(*args, content=body["message"]).stdout.strip()
                self.authors[sha] = self.bot
                return 201, {"sha": sha}
            if route == "/git/refs":
                if self.sha(body["ref"]):
                    return 422, {}
                self.git("update-ref", body["ref"], body["sha"])
                return self.failure("ref") or (201, {"object": {"sha": body["sha"]}})
            if route == "/pulls":
                self.pending_pr = body
                if self.before_pr_create:
                    callback, self.before_pr_create = self.before_pr_create, None
                    callback()
                if any(
                    p["state"] == "open" and p["head"]["ref"] == body["head"]
                    for p in self.prs.values()
                ):
                    return 422, {}
                pr = self.add_pr()
                return self.failure("pr") or (201, pr)
            if route.startswith("/issues/"):
                comment = {
                    "id": len(self.comments) + 100,
                    "body": body["body"],
                    "user": {"login": self.bot, "type": "Bot"},
                }
                self.comments.append(comment)
                return self.failure("report") or (201, comment)
        if method == "PATCH":
            if route.startswith("/git/refs/heads/"):
                if self.before_ref_update:
                    callback, self.before_ref_update = self.before_ref_update, None
                    callback()
                branch = route[len("/git/refs/heads/") :]
                old = self.sha(branch)
                if (
                    body["force"]
                    or self.git(
                        "merge-base",
                        "--is-ancestor",
                        old,
                        body["sha"],
                        check=False,
                    ).returncode
                ):
                    return 422, {}
                self.git("update-ref", "refs/heads/" + branch, body["sha"])
                return self.failure("ref") or (200, {"object": {"sha": body["sha"]}})
            if route.startswith("/pulls/"):
                pr = self.prs[int(route.rsplit("/", 1)[-1])]
                pr.update(body)
                return 200, self.current_pr(pr["number"])
        return 404, {"message": f"Unknown fixture route: {method} {route}"}

    @staticmethod
    def page(records, query):
        page = int(query.get("page", [1])[0])
        size = int(query.get("per_page", [100])[0])
        return 200, copy.deepcopy(records[(page - 1) * size : page * size])
