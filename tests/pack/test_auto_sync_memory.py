"""Tier A and Tier B verification tests for Loopwright Turnkey Memory in gpustack/runner."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

# Subprocess calls invoke fixed node, git, and bash binaries in isolated temp dirs.
# ruff: noqa: S603

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_SCRIPT_PATH = REPO_ROOT / ".auto-sync" / "checks" / "validate_candidate.py"
LINT_WORKFLOWS_SCRIPT_PATH = REPO_ROOT / ".auto-sync" / "checks" / "lint_workflows.py"
TASKPACK_PATH = REPO_ROOT / ".auto-sync" / "taskpack.yaml"
DIGESTS_LOCK_PATH = REPO_ROOT / ".auto-sync" / "digests.lock.json"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "auto-sync.yml"
DOCS_PATH = REPO_ROOT / "docs" / "release-automation.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prev_dont_write
    return module


validate_candidate = _load_module("validate_candidate", VALIDATE_SCRIPT_PATH)
lint_workflows = _load_module("lint_workflows", LINT_WORKFLOWS_SCRIPT_PATH)


NODE_BIN = shutil.which("node")
GIT_BIN = shutil.which("git") or "git"
BASH_BIN = shutil.which("bash") or "/bin/bash"
HAS_NODE = NODE_BIN is not None


def _is_taskpack_v2_loopwright(candidate: Path) -> bool:
    cli_js = candidate / "packages" / "cli" / "dist" / "main.js"
    action_js = candidate / "packages" / "github-app" / "dist" / "action.js"
    index_js = candidate / "packages" / "github-app" / "dist" / "index.js"
    if not (cli_js.is_file() and action_js.is_file() and index_js.is_file()):
        return False
    return "digest sync" in cli_js.read_text(encoding="utf-8", errors="ignore")


def _resolve_loopwright_root() -> Path | None:
    env_root = os.environ.get("LOOPWRIGHT_REPO_ROOT", "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(REPO_ROOT.parent / "loopwright")
    if REPO_ROOT.parent.parent.is_dir():
        lw_ws_dir = REPO_ROOT.parent.parent / "loopwright"
        if lw_ws_dir.is_dir():
            candidates.append(lw_ws_dir)
            for sub_dir in sorted(lw_ws_dir.iterdir()):
                if sub_dir.is_dir():
                    candidates.append(sub_dir)
    try:
        common_git = Path(
            subprocess.check_output(
                [GIT_BIN, "-C", str(REPO_ROOT), "rev-parse", "--git-common-dir"],
                text=True,
            ).strip(),
        ).resolve()
        checkout_root = common_git.parent
        candidates.append(checkout_root.parent / "loopwright")
        if checkout_root.parent.parent.is_dir():
            for org_dir in sorted(checkout_root.parent.parent.iterdir()):
                if org_dir.is_dir():
                    candidates.append(org_dir / "loopwright")
    except (OSError, subprocess.CalledProcessError):
        pass
    for candidate in candidates:
        if _is_taskpack_v2_loopwright(candidate):
            return candidate.resolve()
    return None


LOOPWRIGHT_ROOT = _resolve_loopwright_root()


# ============================================================================
# Tier A: Pure Python Contract Tests (Always run in gpustack/runner CI)
# ============================================================================


def test_taskpack_memory_and_upstreams_contract() -> None:
    manifest = yaml.safe_load(TASKPACK_PATH.read_text(encoding="utf-8"))
    assert manifest["apiVersion"] == "loopwright.dev/v1alpha1"
    assert manifest["kind"] == "Taskpack"
    assert manifest["metadata"]["name"] == "auto-sync"

    execution = manifest["spec"]["execution"]
    assert execution["mode"] == "strict"
    assert execution["digests"]["pinDigests"] is True
    assert DIGESTS_LOCK_PATH.is_file()

    writable = manifest["spec"]["scope"]["writable"]
    protected = manifest["spec"]["scope"]["protected"]
    assert "pack/cuda/**" in writable
    assert "pack/rocm/**" in writable
    assert "pack/cann/**" in writable
    assert "pack/cann/patches/hixl/**" in protected
    for bare in ("pack/cuda", "pack/rocm", "pack/cann", "pack/cann/patches/hixl"):
        assert bare not in writable
        assert bare not in protected

    static_checks = [
        c
        for c in manifest["spec"]["verification"]["localChecks"]
        if c["id"] == "runner-static-checks"
    ]
    assert len(static_checks) == 1
    assert static_checks[0]["parameters"]["allowReadOnlyGitHubToken"] is False
    assert static_checks[0]["parameters"]["toolchainPaths"] == [
        "/usr/local/bin",
        "/usr/bin",
    ]

    memory = manifest["spec"]["memory"]
    assert memory == {
        "directory": ".auto-sync/memory",
        "apply": "separate-pull-request",
        "onNoModelBudget": "deterministic-observations-only",
    }

    for upstream in manifest["spec"]["upstreams"]:
        assert upstream["kind"] == "github-release"
        assert upstream["watchedPaths"] == []


def test_auto_sync_workflow_scrubbed_diagnostics_and_dry_run_alignment() -> None:
    assert lint_workflows.main([str(WORKFLOW_PATH)]) == 0
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "publication-endpoint-url" not in workflow_text

    workflow = yaml.safe_load(workflow_text)
    assert workflow["name"] == "Auto Sync"
    steps = workflow["jobs"]["sync"]["steps"]

    fetch_steps = [s for s in steps if s.get("name") == "Fetch PR head"]
    assert len(fetch_steps) == 1
    assert fetch_steps[0].get("if") == "github.event_name == 'issue_comment'"
    assert (
        "refs/pull/${PR_NUMBER}/head:refs/remotes/origin/pr/${PR_NUMBER}"
        in fetch_steps[0]["run"]
    )

    run_steps = [s for s in steps if s.get("name") == "Run Loopwright"]
    assert len(run_steps) == 1
    run_with = run_steps[0]["with"]
    assert "publication-endpoint-url" not in run_with
    assert "upstream-records" not in run_with
    assert "allow-custom-base-url" not in run_with
    assert run_with["mode"] == "auto"
    assert run_with["allow-privileged-execution"] == "false"
    assert run_with["allow-workflow-writes"] == "false"
    assert run_with["output"] == "json,github-step-summary"
    assert "inputs.force" in run_with["force"]

    upload_steps = [s for s in steps if s.get("name") == "Upload diagnostics"]
    assert len(upload_steps) == 1
    upload_path = upload_steps[0]["with"]["path"]
    for required_pattern in (
        "**/run.json",
        "**/memory-publication.json",
        "**/artifacts/**/*.json",
        "lw-action-*/config/config.yaml",
        "lw-action-*/registry/registry.yaml",
        "!${{ runner.temp }}/loopwright-runs/**/secrets.json",
        "!${{ runner.temp }}/loopwright-runs/**/*.sqlite*",
    ):
        assert required_pattern in upload_path


def test_release_automation_docs_document_turnkey_memory() -> None:
    docs_text = DOCS_PATH.read_text(encoding="utf-8")
    for expected in (
        "digests.lock.json",
        "mode: auto",
        "loopwright/memory/auto-sync/main",
        "memory-pr-url",
        "memory-publication.json",
        "active-snapshot.md",
    ):
        assert expected in docs_text


# ============================================================================
# Tier B: Live @loopwright/github-app + @loopwright/memory Node Bridge Tests
# ============================================================================


@pytest.mark.skipif(
    LOOPWRIGHT_ROOT is None or not HAS_NODE,
    reason="Built Loopwright v2 checkout not present; skipping Tier B live Node bridge tests",
)
def test_tier_b_action_dry_run_compiles_runner_taskpack(tmp_path: Path) -> None:
    assert LOOPWRIGHT_ROOT is not None
    assert NODE_BIN is not None
    cli_js = LOOPWRIGHT_ROOT / "packages" / "cli" / "dist" / "main.js"
    action_js = LOOPWRIGHT_ROOT / "packages" / "github-app" / "dist" / "action.js"
    gh_app_js = LOOPWRIGHT_ROOT / "packages" / "github-app" / "dist" / "index.js"

    digest_res = subprocess.run(
        [
            NODE_BIN,
            str(cli_js),
            "digest",
            "sync",
            "--taskpack",
            ".auto-sync/taskpack.yaml",
            "--repo",
            str(REPO_ROOT),
            "--check",
            "--json",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    digest_payload = json.loads(digest_res.stdout)
    assert digest_payload["data"]["ok"] is True

    schema_script = f"""
import {{ readFileSync }} from 'node:fs';
import {{ parseTaskpackDocument, validateTaskpackV2Manifest }} from {json.dumps(str(gh_app_js))};
const raw = parseTaskpackDocument(readFileSync({json.dumps(str(TASKPACK_PATH))}), '.auto-sync/taskpack.yaml');
const v2 = validateTaskpackV2Manifest(raw, {{
  controlRoot: '.auto-sync',
  manifestPath: '.auto-sync/taskpack.yaml',
}});
console.log(JSON.stringify({{ name: v2.metadata.name, mode: v2.spec.execution?.mode, pinDigests: v2.spec.execution?.digests.pinDigests }}));
"""
    schema_res = subprocess.run(
        [NODE_BIN, "--input-type=module", "-e", schema_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(schema_res.stdout) == {
        "name": "auto-sync",
        "mode": "strict",
        "pinDigests": True,
    }

    run_root = (tmp_path / "runs").resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    summary_file = tmp_path / "summary.md"
    output_file = tmp_path / "output.txt"
    summary_file.write_text("", encoding="utf-8")
    output_file.write_text("", encoding="utf-8")

    head_sha = subprocess.check_output(
        [GIT_BIN, "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()

    base_env = {
        **os.environ,
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKSPACE": str(REPO_ROOT),
        "GITHUB_REPOSITORY": "gpustack/runner",
        "GITHUB_SHA": head_sha,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_STEP_SUMMARY": str(summary_file),
        "GITHUB_OUTPUT": str(output_file),
        "INPUT_TASKPACK-PATH": ".auto-sync/taskpack.yaml",
        "INPUT_MODE": "auto",
        "INPUT_ALLOW-PRIVILEGED-EXECUTION": "false",
        "INPUT_ALLOW-WORKFLOW-WRITES": "false",
        "INPUT_OUTPUT": "json,github-step-summary",
        "INPUT_DRY-RUN": "true",
        "INPUT_RUN-ROOT": str(run_root),
    }
    nc_res = subprocess.run(
        [NODE_BIN, str(action_js)],
        cwd=str(REPO_ROOT),
        env={**base_env, "INPUT_FORCE": "false"},
        capture_output=True,
        text=True,
        check=True,
    )
    nc_payload = json.loads(nc_res.stdout)
    assert nc_payload["kind"] == "no_change"
    assert nc_payload["taskpack"]["name"] == "auto-sync"
    assert nc_payload["delegateOutcome"] is None

    cand_res = subprocess.run(
        [NODE_BIN, str(action_js)],
        cwd=str(REPO_ROOT),
        env={**base_env, "INPUT_FORCE": "true"},
        capture_output=True,
        text=True,
        check=True,
    )
    cand_payload = json.loads(cand_res.stdout)
    assert cand_payload["kind"] == "compiled"
    assert cand_payload["taskpack"]["name"] == "auto-sync"
    assert cand_payload["intake"]["kind"] == "discover"
    assert cand_payload["intake"]["disposition"] == "ready"
    assert cand_payload["delegateOutcome"] is None


@pytest.mark.skipif(
    LOOPWRIGHT_ROOT is None or not HAS_NODE,
    reason="Built Loopwright checkout not present; skipping Tier B live Node bridge tests",
)
def test_tier_b_settled_cycles_publish_memory_pr_and_inject_active_memory(
    tmp_path: Path,
) -> None:
    assert LOOPWRIGHT_ROOT is not None
    assert NODE_BIN is not None
    cli_js = LOOPWRIGHT_ROOT / "packages" / "cli" / "dist" / "main.js"
    gh_app_js = LOOPWRIGHT_ROOT / "packages" / "github-app" / "dist" / "index.js"

    resolved_tmp = tmp_path.resolve()
    bare_remote = resolved_tmp / "remote.git"
    work_repo = resolved_tmp / "repo"
    run_root = resolved_tmp / "runs"
    run_root.mkdir(parents=True, exist_ok=True)

    git_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(resolved_tmp),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Test Bot",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test Bot",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    subprocess.run(
        [GIT_BIN, "init", "--bare", "--initial-branch=main", str(bare_remote)],
        check=True,
        env=git_env,
        capture_output=True,
    )

    tracked = (
        subprocess.check_output([GIT_BIN, "-C", str(REPO_ROOT), "ls-files", "-z"])
        .decode("utf-8")
        .split("\0")
    )
    for rel in tracked:
        if not rel:
            continue
        src = REPO_ROOT / rel
        if not src.is_file() or src.is_symlink():
            continue
        dst = work_repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.stat().st_size > 1_048_576:
            dst.write_bytes(b"placeholder-tarball-under-1mb\n")
        else:
            shutil.copy2(src, dst)

    for sync_rel in (
        ".auto-sync/taskpack.yaml",
        ".auto-sync/digests.lock.json",
        ".auto-sync/instructions.md",
        ".auto-sync/checks/validate_candidate.sh",
        ".auto-sync/checks/validate_candidate.py",
        ".auto-sync/checks/lint_workflows.py",
    ):
        sync_dst = work_repo / sync_rel
        sync_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / sync_rel, sync_dst)

    subprocess.run(
        [GIT_BIN, "init", "--initial-branch=main", str(work_repo)],
        check=True,
        env=git_env,
        capture_output=True,
    )
    subprocess.run(
        [GIT_BIN, "-C", str(work_repo), "remote", "add", "origin", str(bare_remote)],
        check=True,
        env=git_env,
        capture_output=True,
    )
    subprocess.run(
        [GIT_BIN, "-C", str(work_repo), "add", "-A"],
        check=True,
        env=git_env,
        capture_output=True,
    )
    subprocess.run(
        [GIT_BIN, "-C", str(work_repo), "commit", "-m", "chore: initial fixture"],
        check=True,
        env=git_env,
        capture_output=True,
    )
    subprocess.run(
        [GIT_BIN, "-C", str(work_repo), "push", "-u", "origin", "main"],
        check=True,
        env=git_env,
        capture_output=True,
    )

    prs: list[dict[str, object]] = []
    vllm_tag = ["v0.33.0"]
    sglang_tag = ["v0.5.23"]
    ascend_tag = ["v0.32.0rc1"]

    def current_mem_sha() -> str:
        res = subprocess.run(
            [
                GIT_BIN,
                "-C",
                str(bare_remote),
                "rev-parse",
                "--verify",
                "refs/heads/loopwright/memory/auto-sync/main",
            ],
            env=git_env,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout.strip() if res.returncode == 0 else ""

    class MockGitHubHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            pass

        def _send_json(self, code: int, obj: object) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if "/repos/vllm-project/vllm/releases/latest" in self.path:
                self._send_json(
                    200,
                    {"tag_name": vllm_tag[0], "draft": False, "prerelease": False},
                )
                return
            if "/repos/vllm-project/vllm/releases" in self.path:
                self._send_json(
                    200,
                    [{"tag_name": vllm_tag[0], "draft": False, "prerelease": False}],
                )
                return
            if "/repos/sgl-project/sglang/releases/latest" in self.path:
                self._send_json(
                    200,
                    {"tag_name": sglang_tag[0], "draft": False, "prerelease": False},
                )
                return
            if "/repos/sgl-project/sglang/releases" in self.path:
                self._send_json(
                    200,
                    [
                        {
                            "tag_name": sglang_tag[0],
                            "draft": False,
                            "prerelease": False,
                        },
                    ],
                )
                return
            if "/repos/vllm-project/vllm-ascend/releases/latest" in self.path:
                self._send_json(
                    200,
                    {"tag_name": ascend_tag[0], "draft": False, "prerelease": True},
                )
                return
            if "/repos/vllm-project/vllm-ascend/releases" in self.path:
                self._send_json(
                    200,
                    [{"tag_name": ascend_tag[0], "draft": False, "prerelease": True}],
                )
                return
            if self.path == "/repos/gpustack/runner":
                self._send_json(
                    200,
                    {
                        "id": 12345,
                        "full_name": "gpustack/runner",
                        "default_branch": "main",
                    },
                )
                return
            if "/pulls" in self.path:
                sha = current_mem_sha()
                for pr in prs:
                    head_dict = pr["head"]
                    assert isinstance(head_dict, dict)
                    head_dict["sha"] = sha
                self._send_json(200, prs)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path.endswith("/pulls"):
                pr: dict[str, object] = {
                    "number": len(prs) + 1,
                    "html_url": f"https://github.com/gpustack/runner/pull/{len(prs) + 1}",
                    "title": payload.get("title", ""),
                    "body": payload.get("body", ""),
                    "state": "open",
                    "head": {
                        "ref": payload.get("head", "loopwright/memory/auto-sync/main"),
                        "sha": current_mem_sha(),
                        "repo": {"full_name": "gpustack/runner"},
                    },
                    "base": {
                        "ref": payload.get("base", "main"),
                        "repo": {"full_name": "gpustack/runner"},
                    },
                }
                prs.append(pr)
                self._send_json(201, pr)
                return
            self.send_response(404)
            self.end_headers()

        def do_PATCH(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if prs:
                for key in ("title", "body"):
                    if key in payload:
                        prs[0][key] = payload[key]
                head_dict = prs[0]["head"]
                assert isinstance(head_dict, dict)
                head_dict["sha"] = current_mem_sha()
                self._send_json(200, prs[0])
                return
            self._send_json(200, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockGitHubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api_url = f"http://127.0.0.1:{port}"
    step_env = {
        **git_env,
        "GITHUB_API_URL": api_url,
        "LOOPWRIGHT_REPOSITORY": "gpustack/runner",
        "PYTHON_BIN": sys.executable,
    }

    try:
        action_js = LOOPWRIGHT_ROOT / "packages" / "github-app" / "dist" / "action.js"
        init_sha = subprocess.check_output(
            [GIT_BIN, "-C", str(work_repo), "rev-parse", "HEAD"],
            env=git_env,
            text=True,
        ).strip()
        live_nc = subprocess.run(
            [NODE_BIN, str(action_js)],
            cwd=str(work_repo),
            env={
                **step_env,
                "GITHUB_ACTIONS": "true",
                "GITHUB_WORKSPACE": str(work_repo),
                "GITHUB_REPOSITORY": "gpustack/runner",
                "GITHUB_SHA": init_sha,
                "GITHUB_EVENT_NAME": "schedule",
                "GITHUB_TOKEN": "ghs_test_token_123456",
                "INPUT_TASKPACK-PATH": ".auto-sync/taskpack.yaml",
                "INPUT_MODE": "auto",
                "INPUT_ALLOW-PRIVILEGED-EXECUTION": "false",
                "INPUT_ALLOW-WORKFLOW-WRITES": "false",
                "INPUT_DRY-RUN": "false",
                "INPUT_FORCE": "false",
                "INPUT_OUTPUT": "json",
                "INPUT_RUN-ROOT": str(run_root),
                "INPUT_RUN-ID": "run-auto-nc-live",
            },
            capture_output=True,
            text=True,
            check=True,
        )
        live_nc_payload = json.loads(live_nc.stdout)
        assert live_nc_payload["kind"] == "no_change"
        assert live_nc_payload["delegateOutcome"]["ok"] is True

        def run_cycle(
            run_id: str,
            mode: str,
            status: str,
            reason: str,
            mutate_fn=None,
        ) -> str:
            nxt = subprocess.run(
                [
                    NODE_BIN,
                    str(cli_js),
                    "step",
                    "next",
                    "--taskpack",
                    ".auto-sync/taskpack.yaml",
                    "--repo",
                    str(work_repo),
                    "--run-root",
                    str(run_root),
                    "--run-id",
                    run_id,
                    "--mode",
                    mode,
                    "--json",
                ],
                cwd=str(work_repo),
                env=step_env,
                capture_output=True,
                text=True,
                check=True,
            )
            env_obj = json.loads(nxt.stdout)
            attempt_idx = 0
            while env_obj["kind"] == "step":
                step_data = env_obj["data"]
                attempt_idx += 1
                if mutate_fn is not None:
                    mutate_fn(Path(step_data["candidateDir"]), attempt_idx)
                sub = subprocess.run(
                    [
                        NODE_BIN,
                        str(cli_js),
                        "step",
                        "submit",
                        "--run-root",
                        str(run_root),
                        "--run-id",
                        run_id,
                        "--lease",
                        step_data["leaseToken"],
                        "--status",
                        status,
                        "--reason",
                        reason,
                        "--json",
                    ],
                    cwd=str(work_repo),
                    env=step_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                env_obj = json.loads(sub.stdout)
            return env_obj["data"]["result"]["spec"]["status"]

        assert (
            run_cycle(
                "run-nochange-0",
                "no-change",
                "no_change",
                "all upstreams already match proposal",
            )
            == "no_change"
        )

        vllm_tag[0] = "v0.34.0"

        def mutate_static_check_failure(cand_dir: Path, attempt_idx: int) -> None:
            prop_p = cand_dir / ".auto-sync" / "proposal.json"
            (cand_dir / ".auto-sync").chmod(0o755)
            prop_p.chmod(0o644)
            data = json.loads(prop_p.read_text(encoding="utf-8"))
            data["versions"]["vllm"] = f"v0.99.{attempt_idx}"
            prop_p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            prop_p.chmod(0o444)
            (cand_dir / ".auto-sync").chmod(0o555)

        assert run_cycle(
            "run-blocked-1",
            "candidate",
            "completed",
            "attempted unaligned vllm version",
            mutate_static_check_failure,
        ) in {"failed", "blocked", "exhausted"}

        def mutate_readme(cand_dir: Path, attempt_idx: int) -> None:
            del attempt_idx
            readme_p = cand_dir / "README.md"
            cand_dir.chmod(0o755)
            readme_p.chmod(0o644)
            txt = readme_p.read_text(encoding="utf-8")
            if not txt.endswith("\n\n"):
                readme_p.write_text(txt + "\n", encoding="utf-8")
            readme_p.chmod(0o444)
            cand_dir.chmod(0o555)

        assert (
            run_cycle(
                "run-completed-2",
                "candidate",
                "completed",
                "aligned README spacing",
                mutate_readme,
            )
            == "completed"
        )

        head_sha = subprocess.check_output(
            [GIT_BIN, "-C", str(work_repo), "rev-parse", "HEAD"],
            env=git_env,
            text=True,
        ).strip()

        for rid, expected_status in (
            ("run-nochange-0", "no_entries"),
            ("run-blocked-1", "skipped"),
            ("run-completed-2", "published"),
        ):
            pub_script = f"""
import {{ finalizeAndPublishTurnkeyMemory, loadDeclarativeTaskpack, SecretScrubber }} from {json.dumps(str(gh_app_js))};

const manifest = await loadDeclarativeTaskpack({{
  manifestPath: '.auto-sync/taskpack.yaml',
  repositoryRoot: {json.dumps(str(work_repo))},
}});
const res = await finalizeAndPublishTurnkeyMemory({{
  repositoryRoot: {json.dumps(str(work_repo))},
  repositoryFullName: 'gpustack/runner',
  targetBranch: 'main',
  baseRevision: {json.dumps(head_sha)},
  runRoot: {json.dumps(str(run_root))},
  runId: {json.dumps(rid)},
  manifest,
  taskpackPath: '.auto-sync/taskpack.yaml',
  upstreamRecords: [
    {{ upstreamId: 'vllm', status: 'available', version: 'v0.34.0' }},
    {{ upstreamId: 'sglang', status: 'up_to_date', version: 'v0.5.23' }},
    {{ upstreamId: 'vllm-ascend', status: 'up_to_date', version: 'v0.32.0rc1' }},
  ],
  scrubber: new SecretScrubber(),
  remoteUrl: {json.dumps(str(bare_remote))},
  githubToken: 'ghs_test_token_123456',
  apiBaseUrl: {json.dumps(api_url)},
}});
console.log(JSON.stringify(res));
"""
            pub = subprocess.run(
                [NODE_BIN, "--input-type=module", "-e", pub_script],
                env=step_env,
                capture_output=True,
                text=True,
                check=True,
            )
            pub_json = json.loads(pub.stdout)
            assert pub_json["status"] == expected_status
            if expected_status == "published":
                assert (
                    pub_json["pullRequestUrl"]
                    == "https://github.com/gpustack/runner/pull/1"
                )
                receipt = json.loads(
                    (run_root / rid / "memory-publication.json").read_text(
                        encoding="utf-8",
                    ),
                )
                assert receipt["state"] == "completed"

        branch_files = subprocess.check_output(
            [
                GIT_BIN,
                "-C",
                str(bare_remote),
                "ls-tree",
                "-r",
                "--name-only",
                "refs/heads/loopwright/memory/auto-sync/main",
            ],
            env=git_env,
            text=True,
        ).splitlines()
        mem_files = [f for f in branch_files if f.startswith(".auto-sync/memory/")]
        assert ".auto-sync/memory/auto-sync/index.json" in mem_files
        assert any(
            f.startswith(".auto-sync/memory/auto-sync/entries/") and f.endswith(".md")
            for f in mem_files
        )
        assert all(
            f
            in (".auto-sync/memory/.gitkeep", ".auto-sync/memory/auto-sync/index.json")
            or (
                f.startswith(".auto-sync/memory/auto-sync/entries/")
                and f.endswith(".md")
            )
            for f in mem_files
        )

        subprocess.run(
            [
                GIT_BIN,
                "-C",
                str(work_repo),
                "fetch",
                "origin",
                "loopwright/memory/auto-sync/main",
            ],
            check=True,
            env=git_env,
            capture_output=True,
        )
        subprocess.run(
            [GIT_BIN, "-C", str(work_repo), "merge", "--ff-only", "FETCH_HEAD"],
            check=True,
            env=git_env,
            capture_output=True,
        )

        val_res = subprocess.run(
            [BASH_BIN, ".auto-sync/checks/validate_candidate.sh"],
            cwd=str(work_repo),
            env={**git_env, "PYTHON_BIN": str(REPO_ROOT / ".venv" / "bin" / "python")},
            capture_output=True,
            text=True,
            check=False,
        )
        assert val_res.returncode == 0, val_res.stderr

        r3_next = subprocess.run(
            [
                NODE_BIN,
                str(cli_js),
                "step",
                "next",
                "--taskpack",
                ".auto-sync/taskpack.yaml",
                "--repo",
                str(work_repo),
                "--run-root",
                str(run_root),
                "--run-id",
                "run-next-3",
                "--mode",
                "candidate",
                "--json",
            ],
            cwd=str(work_repo),
            env=step_env,
            capture_output=True,
            text=True,
            check=True,
        )
        y3 = json.loads(r3_next.stdout)["data"]
        assert "<active_memory>" in y3["prompt"]
        snapshot_paths = [
            Path(p)
            for p in y3["contextFiles"]
            if p.endswith(".auto-sync/memory/auto-sync/active-snapshot.md")
        ]
        assert len(snapshot_paths) == 1
        assert snapshot_paths[0].is_file()
        assert "Verified Facts" in snapshot_paths[0].read_text(encoding="utf-8")
    finally:
        server.shutdown()
