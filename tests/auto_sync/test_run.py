"""Public upstream acquisition: optional bearer token and rate-limit semantics."""

import json
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.auto_sync import proposal, run


class Upstream:
    """Canned GitHub API boundary recording request headers."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __enter__(self):
        fixture = self

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                fixture.requests.append((self.path, dict(self.headers)))
                route = fixture.routes.get(self.path)
                if route is None:
                    self.send_error(404)
                    return
                status, headers, payload = route
                data = json.dumps(payload).encode()
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def authorization(self):
        return self.requests[0][1].get("Authorization")


@pytest.fixture
def upstream_env(monkeypatch):
    monkeypatch.delenv("AUTO_SYNC_UPSTREAM_TOKEN", raising=False)
    return monkeypatch


def test_anonymous_without_token(upstream_env):
    with Upstream({"/repos/a/b/releases": (200, {}, [])}) as api:
        upstream_env.setenv("GITHUB_API_URL", api.url)
        assert run.PublicUpstream().get("/repos/a/b/releases") == []
    assert api.authorization() is None


def test_bearer_token_sent_only_when_configured(upstream_env):
    with Upstream({"/repos/a/b/releases": (200, {}, [])}) as api:
        upstream_env.setenv("GITHUB_API_URL", api.url)
        upstream_env.setenv("AUTO_SYNC_UPSTREAM_TOKEN", "fake-read-token")
        assert run.PublicUpstream().get("/repos/a/b/releases") == []
    assert api.authorization() == "Bearer fake-read-token"


def test_token_never_leaks_into_errors(upstream_env):
    routes = {"/repos/a/b/releases": (403, {}, {"message": "Forbidden"})}
    with Upstream(routes) as api:
        upstream_env.setenv("GITHUB_API_URL", api.url)
        upstream_env.setenv("AUTO_SYNC_UPSTREAM_TOKEN", "fake-read-token")
        with pytest.raises(proposal.ProposalError) as caught:
            run.PublicUpstream().get("/repos/a/b/releases")
    assert str(caught.value) == "upstream query failed (403)"
    assert "fake-read-token" not in str(caught.value)


def test_primary_rate_limit_names_reset_and_rerun(upstream_env):
    reset = 1800000000
    headers = {
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(reset),
    }
    routes = {
        "/repos/a/b/releases": (403, headers, {"message": "API rate limit exceeded"}),
    }
    with Upstream(routes) as api:
        upstream_env.setenv("GITHUB_API_URL", api.url)
        with pytest.raises(proposal.ProposalError) as caught:
            run.PublicUpstream().get("/repos/a/b/releases")
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset))
    message = str(caught.value)
    assert "rate-limited (403)" in message
    assert when in message
    assert "re-run the failed job" in message


def test_secondary_rate_limit_names_retry_after(upstream_env):
    routes = {
        "/repos/a/b/releases": (
            429,
            {"Retry-After": "60"},
            {"message": "secondary rate limit"},
        ),
    }
    with Upstream(routes) as api:
        upstream_env.setenv("GITHUB_API_URL", api.url)
        with pytest.raises(proposal.ProposalError) as caught:
            run.PublicUpstream().get("/repos/a/b/releases")
    message = str(caught.value)
    assert "rate-limited (429)" in message
    assert "retry after 60s" in message
    assert "re-run the failed job" in message


def test_plain_forbidden_stays_generic(upstream_env):
    routes = {"/repos/a/b/releases": (403, {}, {"message": "Forbidden"})}
    with Upstream(routes) as api:
        upstream_env.setenv("GITHUB_API_URL", api.url)
        with pytest.raises(proposal.ProposalError) as caught:
            run.PublicUpstream().get("/repos/a/b/releases")
    assert str(caught.value) == "upstream query failed (403)"
