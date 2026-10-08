"""Local public upstream and OCI boundaries backed by real Git and image data."""

import hashlib
import json
import os
import subprocess
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from service import FakeGitHub


def encoded(value):
    data = json.dumps(value, separators=(",", ":")).encode()
    return data, "sha256:" + hashlib.sha256(data).hexdigest()


class Upstreams(FakeGitHub):
    def __init__(self, repo, repository, bot, upstream, clone_url):
        super().__init__(repo, repository, bot)
        self.upstream = upstream
        self.clone_url = clone_url
        self.releases = {
            "vllm-project/vllm": [self.release("0.30.0"), self.release("0.29.0")],
            "sgl-project/sglang": [self.release("0.5.0")],
            "vllm-project/vllm-ascend": [
                self.release("0.30.0rc1", "- **Upstream vLLM**: v0.30.0.", True),
            ],
        }
        self.outages = set()
        self.delays = {}
        self.source_revisions = {}

    @staticmethod
    def release(version, body="", prerelease=False):
        return {
            "tag_name": "v" + version,
            "draft": False,
            "prerelease": prerelease,
            "body": body,
        }

    def request(self, method, url, body):
        path = urlsplit(url).path
        for name, records in self.releases.items():
            prefix = "/repos/" + name
            if path.startswith(prefix):
                if name in self.delays:
                    time.sleep(self.delays[name])
                if name in self.outages:
                    return 503, {}
                if path == prefix + "/releases":
                    return self.page(records, parse_qs(urlsplit(url).query))
                if path == prefix:
                    return 200, {"clone_url": self.clone_url}
                if path.startswith(prefix + "/commits/"):
                    revision = unquote(path[len(prefix + "/commits/") :])
                    sha = self.source_revisions.get((name, revision), self.upstream)
                    return (200, {"sha": sha}) if sha is not None else (404, {})
        status, result = super().request(method, url, body)
        if path == "/repos/" + self.repository and method == "GET":
            result["clone_url"] = self.clone_url.replace(
                "upstream/.git",
                "objects/.git",
            )
        return status, result


class Registry:
    def __init__(self, platform=None, config_platform=None):
        platform = platform or {"os": "linux", "architecture": "amd64"}
        config, config_digest = encoded(config_platform or platform)
        child, child_digest = encoded(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": config_digest,
                    "size": len(config),
                },
                "layers": [],
            },
        )
        index, index_digest = encoded(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": child_digest,
                        "size": len(child),
                        "platform": platform,
                    },
                ],
            },
        )
        self.index_digest = index_digest
        self.child_digest = child_digest
        self.objects = {index_digest: index, child_digest: child, config_digest: config}
        self.requests = []

    def __enter__(self):
        fixture = self

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.respond(False)

            def do_HEAD(self):
                self.respond(True)

            def respond(self, head):
                fixture.requests.append((self.path, dict(self.headers)))
                if self.path == "/v2/":
                    data, digest = b"{}", None
                else:
                    key = self.path.rsplit("/", 1)[-1]
                    if key == "v0.30.0":
                        key = fixture.index_digest
                    data = fixture.objects.get(key)
                    digest = key
                if data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                media = json.loads(data).get("mediaType", "application/json")
                self.send_header("Content-Type", media)
                if digest:
                    self.send_header("Docker-Content-Digest", digest)
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.image = f"127.0.0.1:{self.server.server_port}/vllm:v0.30.0"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class GitHTTP:
    def __init__(self, root):
        self.root = root

    def __enter__(self):
        root = self.root

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.backend()

            def do_POST(self):
                self.backend()

            def backend(self):
                parsed = urlsplit(self.path)
                env = {
                    "PATH": os.defpath,
                    "GIT_PROJECT_ROOT": str(root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "PATH_INFO": parsed.path,
                    "QUERY_STRING": parsed.query,
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "REMOTE_ADDR": "127.0.0.1",
                    "HOME": str(root),
                }
                content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                result = subprocess.run(
                    ["git", "http-backend"],  # noqa: S607 - controlled local Git protocol.
                    input=content,
                    env=env,
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
                headers, body = result.stdout.split(b"\r\n\r\n", 1)
                values = dict(
                    line.decode().split(": ", 1) for line in headers.split(b"\r\n")
                )
                self.send_response(int(values.pop("Status", "200 OK").split()[0]))
                for key, value in values.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(Handler, directory=str(self.root)),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/upstream/.git"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ExhaustedModel:
    def __enter__(self):
        fixture = self
        self.requests = []

        class Handler(SimpleHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((body, dict(self.headers)))
                self.send_response(402)
                data = b'{"error":{"message":"quota exhausted"}}'
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
