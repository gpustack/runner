# ruff: noqa: PERF203
# Independent acquisition failures must retain each subscription outcome.
"""Trusted stage controller; transport data, never agent workspaces, between jobs."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import string
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests
import yaml

from tools.auto_sync import agent, assemble, checks, discovery, model, proposal, publish
from tools.auto_sync.agent import _print_progress
from tools.auto_sync.checks import _clone, _git, _run
from tools.auto_sync.discovery import _releases as release_versions

HTTP_TIMEOUT = (10, 300)

LLM_INPUTS = (
    "url",
    "model",
    "auth-token",
    "protocol",
    "use-anthropic",
    "thinking",
    "thinking-clear",
    "temperature",
    "top-p",
    "max-tokens",
    "reasoning-effort",
    "timeout",
    "context-window-size",
    "modalities",
    "auth-header",
    "extra-headers",
    "extra-body",
)

PACK_RUN_URL = re.compile(
    r"https://github\.com/([^/]+/[^/]+)/actions/runs/([0-9]+)(?:/job/([0-9]+))?/?",
)

JOB_LOG_LIMIT = 4000

PROMPT_SENTINEL = "=== STAGE INPUT (JSON) ==="
CONTRACT_SENTINEL = "=== OUTPUT CONTRACT ==="
_PROMPT_DIR = Path(__file__).parent / "prompts"


def _prompt_identifiers(text: str) -> set:
    """Placeholder names declared in one template; Python 3.10 has no get_identifiers."""
    found = string.Template.pattern.findall(text)
    return {named or braced for _, named, braced, _ in found if named or braced}


def _prompt(name: str, **values: str) -> str:
    """Render one stage prompt template; placeholder sets must match exactly."""
    text = (_PROMPT_DIR / (name + ".md")).read_text(encoding="utf-8")
    identifiers = _prompt_identifiers(text)
    missing = sorted(identifiers - set(values))
    unused = sorted(set(values) - identifiers)
    proposal.require(
        not missing and not unused,
        f"prompt template {name} placeholder drift: missing {missing}, unused {unused}",
    )
    return string.Template(text).substitute(values)


def prompt_payload(prompt: str) -> str:
    """Payload section of an assembled stage prompt, between the two sentinels."""
    return prompt.split(PROMPT_SENTINEL, 1)[1].split(CONTRACT_SENTINEL, 1)[0]


def _env(home: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("AUTO_SYNC_TOOL_BIN", "")
        + os.pathsep
        + os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "DOCKER_CONFIG": str(home / "docker"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
        "SSH_ASKPASS": "/usr/bin/false",
        "LANG": "C.UTF-8",
    }


def _write(path: Path, data: dict | list) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
    )


def _restore_bundle(path: Path, data: dict) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
    path.mkdir()
    for name, value in data.items():
        _write(path / (name + ".json"), value)


def _read(path: Path):
    proposal.require(
        path.is_file() and not path.is_symlink(),
        "bundle file is missing or a symlink",
    )
    return proposal.load_json(path.read_text())


class PublicUpstream:
    """Anonymous bounded acquisition, also used without secrets in validation."""

    def __init__(self):
        self.url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip(
            "/",
        )
        _public_url(self.url)
        self.session = requests.Session()
        self.session.trust_env = False

    def get(self, path: str):
        try:
            response = self.session.get(
                self.url + path,
                timeout=HTTP_TIMEOUT,
                allow_redirects=False,
            )
            proposal.require(
                response.status_code == 200,
                f"upstream query failed ({response.status_code})",
            )
            return proposal.load_json(response.text)
        except requests.RequestException:
            msg = "upstream query transport failed"
            raise proposal.ProposalError(msg) from None

    def releases(self, name: str) -> list:
        records = []
        for page in range(1, 21):
            rows = self.get(f"/repos/{name}/releases?per_page=100&page={page}")
            proposal.require(isinstance(rows, list), "invalid upstream release array")
            records.extend(rows)
            if len(rows) < 100:
                return records
        msg = "upstream release pagination limit exceeded"
        raise proposal.ProposalError(msg)


def _public_url(url: str) -> None:
    parsed = urlsplit(url)
    proposal.require(
        not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and (
            parsed.scheme == "https"
            or (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1"}
            )
        ),
        "public source URL must be HTTPS without credentials",
    )


def _releases(api: PublicUpstream) -> tuple[dict, dict]:
    releases, errors = {}, {}
    for name in (*discovery.UPSTREAMS.values(), discovery.ASCEND):
        try:
            releases[name] = api.releases(name)
        except (ValueError, TypeError) as exc:
            errors[name] = str(exc)
    return releases, errors


def _pair(records: list) -> dict:
    # Explicit relationship statements support old pending pairs too.
    result = {}
    try:
        eligible = release_versions(records, plugin=True)
    except (ValueError, TypeError, KeyError):
        return result
    for selected in eligible:
        releases = [
            r
            for r in records
            if re.match(r"v?\d", r["tag_name"])
            and discovery.version(r["tag_name"]) == selected
            and not r["draft"]
        ]
        engines = set()
        for release in releases:
            body = release.get("body") or ""
            engines.update(
                re.findall(
                    r"(?im)^\s*-?\s*\*?\*?Upstream vLLM\*?\*?\s*:\s*v?(\d[^\s,;]*)",
                    body,
                ),
            )
            engines.update(
                re.findall(r"(?i)aligned with upstream vLLM\s+v?(\d[^\s,;]*)", body),
            )
        try:
            parsed = {str(discovery.version(value.rstrip("."))) for value in engines}
        except ValueError:
            continue
        if len(parsed) == 1:
            release = releases[0]
            result[str(selected)] = {
                "engine_version": parsed.pop(),
                "source": f"https://github.com/{discovery.ASCEND}/releases/tag/{quote(release['tag_name'], safe='')}",
            }
    # A post release reissues its line's fixes and never changes the engine
    # alignment, so its notes omit the relationship statement; inherit the
    # line base's documented pair instead of blocking the chase forever.
    for selected in eligible:
        if str(selected) in result or not selected.is_postrelease:
            continue
        base = str(discovery.version(".".join(map(str, selected.release))))
        if base in result:
            result[str(selected)] = result[base]
    return result


def _permissions(context: dict) -> set:
    if context["identity"]["mode"] != "revise":
        return set()
    command = context.get("command", {})
    body = command.get("body", "")
    proposal.require(
        command.get("id") == context["identity"]["command_id"]
        and hashlib.sha256(body.encode()).hexdigest()
        == context["identity"]["command_digest"],
        "prerelease authorization comment differs from frozen command",
    )
    # A conservative positive subset; unclear free text grants no permission.
    if re.search(
        r"(?i)\b(not|never|avoid|unless|if|maybe|consider|could|might|or|depending|provided|perhaps|possibly|optionally)\b|don['\u2019]t",
        body,
    ):
        return set()
    result = set()
    for line in body.splitlines()[1:]:
        if not re.match(
            r"(?i)^\s*(?:please\s+)?(?:use|upgrade|update|switch|pin|target|select)\b",
            line,
        ):
            continue
        backends = {v.lower() for v in re.findall(r"(?i)\b(cuda|rocm|cann)\b", line)}
        services = {v.lower() for v in re.findall(r"(?i)\b(vllm|sglang)\b", line)}
        tokens = re.findall(r"(?i)(?<![\w.])v?([0-9][A-Za-z0-9.+-]*)", line)
        try:
            versions = {discovery.version(token.rstrip(".")) for token in tokens}
        except ValueError:
            continue
        if len(backends) != 1 or len(services) != 1 or len(versions) != 1:
            continue
        backend = backends.pop().lower()
        selected = versions.pop()
        if (
            backend not in {"cuda", "rocm"}
            or not selected.is_prerelease
            or selected.is_devrelease
            or selected.local
        ):
            continue
        result.add((backend, services.pop().lower(), str(selected)))
    # Two different requested versions for one combination are ambiguous.
    counts = {(b, service) for b, service, _ in result}
    return result if len(counts) == len(result) else set()


def _package_prereleases(context: dict) -> set:
    """Frozen prerelease whitelist from the default checkout; never candidate input."""
    packages = context.get("prerelease_packages", [])
    proposal.require(
        isinstance(packages, list)
        and all(key in discovery.PRERELEASE_KEYS for key in packages),
        "invalid frozen prerelease packages",
    )
    return set(packages)


def _source(
    api: PublicUpstream,
    name: str,
    revision: str,
    root: Path,
    env: dict,
) -> tuple[Path, str]:
    proposal.require(
        re.fullmatch(proposal.REPOSITORY, name),
        "invalid upstream source repository",
    )
    resolved = api.get(f"/repos/{name}/commits/{quote(revision, safe='')}")["sha"]
    proposal.require(
        re.fullmatch(proposal.SHA, resolved),
        "upstream source did not resolve to an exact commit",
    )
    if re.fullmatch(proposal.SHA, revision):
        proposal.require(
            resolved == revision,
            "upstream exact source revision mismatch",
        )
    target = root / name.replace("/", "-") / resolved
    if not target.exists():
        url = api.get(f"/repos/{name}")["clone_url"]
        _public_url(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "init", "--quiet", str(target)], env)
        _git(
            env,
            target,
            "fetch",
            "--quiet",
            "--depth=1",
            "--no-tags",
            "--",
            url,
            resolved,
        )
        _git(env, target, "checkout", "--quiet", "--detach", resolved)
        proposal.require(
            _git(env, target, "rev-parse", "HEAD").strip() == resolved,
            "source checkout mismatch",
        )
    return target, resolved


def _selected_sources(api, releases, found, root, env, permissions=()):
    sources, evidence, errors = {}, {}, {}
    wanted = {}
    for candidate in found:
        if "engine_version" in candidate:
            wanted[
                (discovery.UPSTREAMS[candidate["service"]], candidate["engine_version"])
            ] = None
        if candidate.get("plugin_version"):
            wanted[(discovery.ASCEND, candidate["plugin_version"])] = None
    for _backend, service, selected in permissions:
        wanted[(discovery.UPSTREAMS[service], selected)] = None
    for name, selected in wanted:
        release = next(
            (
                r
                for r in releases.get(name, [])
                if re.match(r"v?\d", r["tag_name"])
                and discovery.version(r["tag_name"]) == discovery.version(selected)
                and not r["draft"]
            ),
            None,
        )
        if not release:
            continue
        try:
            tree, sha = _source(api, name, release["tag_name"], root, env)
            sources.setdefault(name, {})[sha] = tree
            notes = tree.parent / (sha + ".release.md")
            notes.write_text(release.get("body") or "", encoding="utf-8")
            metadata = tree.parent / (sha + ".release.json")
            _write(metadata, release)
            evidence[f"{name}@{selected}"] = {
                "repository": name,
                "revision": sha,
                "path": str(tree),
                "source": f"https://github.com/{name}/tree/{sha}",
                "release": {
                    key: release[key]
                    for key in ("tag_name", "html_url", "published_at", "prerelease")
                    if key in release
                },
                "release_notes_path": str(notes),
                "release_metadata_path": str(metadata),
            }
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors[f"{name}@{selected}"] = str(exc)
    return sources, evidence, errors


COMPONENT_SOURCES = {
    "OMNI_COMMIT": ("vllm-project/vllm-omni", "{}"),
    "LMCACHE_VERSION": ("LMCache/LMCache", "v{}"),
}


def _recipe_pins(env, repo, sha, backend, service):
    """Effective pins of one recipe from the trusted store at the frozen default."""
    try:
        text = _git(env, repo, "show", f"{sha}:pack/{backend}/Dockerfile.{service}")
    except proposal.ProposalError:
        return {}
    try:
        matrix = yaml.safe_load(_git(env, repo, "show", f"{sha}:pack/matrix.yaml"))
    except proposal.ProposalError:
        matrix = None
    overrides = [
        argument
        for rule in (matrix or {}).get("rules", [])
        if isinstance(rule, dict)
        and rule.get("backend") == backend
        and service in rule.get("services", [])
        for argument in rule.get("args", [])
    ]
    try:
        return checks.recipe_arguments(text, overrides)
    except proposal.ProposalError:
        return {}


def _component_sources(api, repo, sha, found, root, env):
    """
    Exact source trees for the component pins (vllm-omni, LMCache) of recipes.

    Research verifies component patches against these trees. An unresolvable pin
    is recorded instead of failing the run, exactly like engine source errors.
    """
    evidence, errors = {}, {}
    for candidate in found:
        backend, service = candidate["backend"], candidate["service"]
        args = _recipe_pins(env, repo, sha, backend, service)
        for suffix, (name, template) in COMPONENT_SOURCES.items():
            pin = args.get(f"{service.upper()}_{suffix}")
            if pin is None:
                continue
            key = f"{name}@{pin}"
            if key in evidence or key in errors:
                continue
            if not pin:
                errors[key] = "recipe pin is empty"
                continue
            try:
                tree, resolved = _source(api, name, template.format(pin), root, env)
                evidence[key] = {
                    "repository": name,
                    "revision": resolved,
                    "path": str(tree),
                    "source": f"https://github.com/{name}/tree/{resolved}",
                }
            except (ValueError, OSError, KeyError, TypeError) as exc:
                errors[key] = str(exc)
    return evidence, errors


def _registry(row: dict, env: dict) -> dict:
    image = row["base_image"]
    proposal.require(
        re.fullmatch(r"[A-Za-z0-9_.:/@-]+", image),
        "unsafe image reference",
    )
    binary = shutil.which("crane", path=env["PATH"])
    proposal.require(binary is not None, "required registry tool crane is missing")
    # Resolving once, then reading by digest, prevents mixing a moving tag.
    digest = _run([binary, "digest", image], env).strip()
    proposal.require(
        re.fullmatch(proposal.DIGEST, digest),
        "invalid acquired registry digest",
    )
    repository = image.split("@")[0]
    if ":" in repository.rsplit("/", 1)[-1]:
        repository = repository.rsplit(":", 1)[0]
    manifest = proposal.load_json(
        _run([binary, "manifest", repository + "@" + digest], env),
    )
    platform = row["platform"]
    child = digest
    if "manifests" in manifest:
        descriptors = [
            m
            for m in manifest["manifests"]
            if _platform(m.get("platform", {})) == platform
        ]
        proposal.require(
            len(descriptors) == 1,
            "requested image platform is missing or ambiguous",
        )
        child = descriptors[0]["digest"]
    proposal.require(
        re.fullmatch(proposal.DIGEST, child),
        "invalid acquired platform digest",
    )
    config = proposal.load_json(
        _run([binary, "config", repository + "@" + child], env),
    )
    proposal.require(
        _platform(config) == platform,
        "acquired registry configuration platform mismatch",
    )
    return {
        "digest": digest,
        "platform_digest": child,
        "platform": platform,
        "config_platform": _platform(config),
    }


def _platform(value: dict) -> str:
    variant = value.get("variant")
    platform = f"{value.get('os')}/{value.get('architecture')}" + (
        "/" + variant if variant else ""
    )
    return {
        "linux/arm64/v8": "linux/arm64",
        "linux/amd64/v1": "linux/amd64",
    }.get(platform, platform)


def _statuses(data: dict) -> None:
    groups = {g["id"]: g for g in data["groups"]}
    for candidate in data["candidates"]:
        states = {groups[name]["status"] for name in candidate["groups"]}
        if states:
            candidate["status"] = next(
                s for s in ("ready", "failed", "blocked", "unchanged") if s in states
            )


def _bind_discovery(data: dict, context: dict) -> dict:
    if context["identity"]["mode"] != "discover":
        return data
    found = {c["subscription"]: c for c in context["discovery"]}
    for group in data["groups"]:
        try:
            for row in group["rows"]:
                selected = found[f"{row['backend']}/{row['service']}"]
                proposal.require(
                    selected["status"] != "failed",
                    selected.get("reason", "Trusted discovery failed."),
                )
                if group["status"] != "ready":
                    continue
                proposal.require(
                    selected["status"] == "needs_update",
                    "Discovery candidate is already represented or blocked.",
                )
                # A variant outside the discovery universe is not represented:
                # it may be added back with evidence when support returns.
                proposal.require(
                    row["variant"] not in {v["variant"] for v in selected["variants"]}
                    or row["variant"]
                    in {
                        v["variant"]
                        for v in selected["variants"]
                        if v["status"] == "needs_update"
                    },
                    "Discovery variant is already represented or blocked.",
                )
                proposal.require(
                    selected["engine_version"]
                    == str(discovery.version(row["engine_version"]))
                    and selected["plugin_version"] == row["plugin_version"],
                    "Discovery proposal differs from the selected candidate.",
                )
        except proposal.ProposalError as exc:
            group.update(status="failed", reason=str(exc))
    _statuses(data)
    defaults = {c["subscription"]: c for c in _candidates(context["discovery"])}
    for candidate in data["candidates"]:
        selected = found[candidate["subscription"]]
        if not candidate["groups"] and (
            selected["status"] != "needs_update" or candidate["status"] == "unchanged"
        ):
            candidate.update(defaults[candidate["subscription"]])
        elif selected["status"] == "failed":
            candidate["reason"] = selected["reason"]
    return data


def _acquire_candidate(
    raw: dict,
    context: dict,
    scratch: Path,
) -> tuple[dict, dict, dict]:
    permissions = _permissions(context)
    data = _bind_discovery(
        proposal.validate_proposal(
            raw,
            context["identity"],
            engine_prereleases=permissions,
            prerelease_packages=_package_prereleases(context),
        ),
        context,
    )
    api = PublicUpstream()
    releases, errors = _releases(api)
    pairs = _pair(releases.get(discovery.ASCEND, []))
    env = _env(scratch / "home")
    sources = {}
    for group in data["groups"]:
        if group["status"] != "ready":
            continue
        try:
            for row in group["rows"]:
                name = discovery.UPSTREAMS[row["service"]]
                proposal.require(
                    name not in errors,
                    errors.get(name, "upstream query failed"),
                )
                available = release_versions(releases[name])
                if (
                    row["backend"],
                    row["service"],
                    str(discovery.version(row["engine_version"])),
                ) in permissions:
                    available |= {
                        discovery.version(r["tag_name"])
                        for r in releases[name]
                        if not r["draft"] and re.match(r"v?\d", r["tag_name"])
                    }
                proposal.require(
                    discovery.version(row["engine_version"]) in available,
                    "candidate engine is not an acquired upstream release",
                )
                actual = _registry(row, env)
                claimed = {k: row["manifest"][k] for k in actual}
                proposal.require(
                    actual == claimed,
                    "candidate manifest differs from trusted registry acquisition",
                )
                for patch in row["patches"]:
                    if patch["disposition"] == "remove":
                        continue
                    name, selected = _patch_source(patch, row)
                    if patch["source_revision"] is None:
                        continue
                    if name != "vllm-project/vllm-omni":
                        release = next(
                            (
                                r
                                for r in releases.get(name, [])
                                if not r["draft"]
                                and re.match(r"v?\d", r["tag_name"])
                                and discovery.version(r["tag_name"])
                                == discovery.version(selected)
                            ),
                            None,
                        )
                        selected = release["tag_name"] if release else None
                    try:
                        proposal.require(
                            selected is not None,
                            "patch source pin is unknown",
                        )
                        tree, revision = _source(
                            api,
                            name,
                            selected,
                            scratch / "sources",
                            env,
                        )
                    except (ValueError, OSError, KeyError, TypeError):
                        # Unknown targets cannot borrow another patch's acquired source.
                        patch["source_revision"] = None
                        continue
                    proposal.require(
                        patch["source_revision"] == revision,
                        "patch source differs from the selected component revision",
                    )
                    if name in sources and sources[name] != tree:
                        _git(
                            env,
                            sources[name],
                            "fetch",
                            "--quiet",
                            "--",
                            str(tree),
                            revision,
                        )
                    else:
                        sources[name] = tree
        except (ValueError, OSError, TypeError, KeyError) as exc:
            group.update(status="failed", reason=f"Trusted acquisition failed: {exc}")
    _statuses(data)
    return data, sources, pairs


def _patch_source(patch: dict, row: dict) -> tuple[str, str | None]:
    component = Path(patch["path"]).parts[3]
    applicable = row["engine_version"]
    if component == "vllm_ascend":
        name, selected = discovery.ASCEND, row["plugin_version"]
        applicable = selected
    elif component == "vllm_omni":
        name = "vllm-project/vllm-omni"
        # Omni versions describe engine applicability; its package selects the source pin.
        package = next(
            (p for p in row["packages"] if p["name"].lower() == "vllm-omni"),
            None,
        )
        selected = (
            package["version"] if package and package["decision"] != "disable" else None
        )
    else:
        name, selected = discovery.UPSTREAMS[row["service"]], row["engine_version"]
    proposal.require(
        patch["source_repository"] == name,
        "patch repository differs from the selected component repository",
    )
    proposal.require(
        applicable is not None
        and discovery.version(applicable)
        in {discovery.version(v) for v in patch["versions"]},
        "patch versions do not cover the selected component version",
    )
    return name, selected


def _candidates(found: list, *, failed=False, reason=None) -> list:
    return [
        {
            "subscription": c["subscription"],
            "groups": [],
            "status": "failed"
            if failed and c["status"] == "needs_update"
            else "blocked"
            if c["status"] == "needs_update"
            else c["status"],
            "reason": reason
            if failed and c["status"] == "needs_update" and reason
            else c.get(
                "reason",
                "Research is required."
                if c["status"] == "needs_update"
                else "Latest release already represented.",
            ),
        }
        for c in found
    ]


def _result(stage, status, reason, *, candidates=None, **fields):
    return {
        "schema_version": 1,
        "stage": stage,
        "status": status,
        "reason": reason,
        "ready": False,
        "publishable": False,
        "candidates": candidates
        if candidates is not None
        else [
            {
                "subscription": f"{b}/{s}",
                "status": "failed",
                "groups": [],
                "reason": reason,
            }
            for b, s, _ in discovery.SUBSCRIPTIONS
        ]
        if status == "failed"
        else [],
        "durations": {},
        **fields,
    }


def _github():
    return publish.GitHub(
        os.environ.get("AUTO_SYNC_GITHUB_TOKEN", ""),
        os.environ.get("AUTO_SYNC_BOT_LOGIN", ""),
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )


def _ensure_head(repo, context, env):
    sha = context["identity"]["head_sha"]
    try:
        _git(env, repo, "cat-file", "-e", sha + "^{commit}")
    except proposal.ProposalError:
        name = context["identity"]["repository"]
        url = PublicUpstream().get(f"/repos/{name}")["clone_url"]
        _public_url(url)
        _git(
            env,
            repo,
            "fetch",
            "--quiet",
            "--depth=1",
            "--no-tags",
            "--",
            url,
            sha,
        )
        proposal.require(
            _git(env, repo, "rev-parse", sha + "^{commit}").strip() == sha,
            "original PR head acquisition mismatch",
        )
    _git(env, repo, "update-ref", "refs/heads/auto-sync-source-" + sha, sha)


def _job_log_tail(github, repository, job_id) -> str:
    """Fetch the bounded tail of one job log; the API redirects to a signed URL."""
    try:
        with github.session.get(
            f"{github.api_url}/repos/{repository}/actions/jobs/{job_id}/logs",
            timeout=HTTP_TIMEOUT,
            stream=True,
        ) as response:
            if response.status_code != 200:
                return f"<log unavailable: HTTP {response.status_code}>"
            tail = b""
            for chunk in response.iter_content(8192):
                tail = (tail + chunk)[-32768:]
    except requests.RequestException as error:
        return f"<log unavailable: {type(error).__name__}>"
    return tail.decode("utf-8", "replace")[-JOB_LOG_LIMIT:]


def _pack_failure(github, repository, url: str) -> dict:
    """Summarize a supplied Pack run so research can diagnose its failed jobs."""
    match = PACK_RUN_URL.fullmatch(url.strip())
    if match is None or match.group(1) != repository:
        msg = "pack run URL must name an actions run of the trusted repository"
        raise proposal.ProposalError(msg)
    run_id, job_id = match.group(2), match.group(3)
    run = github.request("GET", f"/repos/{repository}/actions/runs/{run_id}")
    jobs = github.request(
        "GET",
        f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
    ).get("jobs", [])
    failed = [
        job
        for job in jobs
        if job.get("conclusion") == "failure"
        and (job_id is None or str(job.get("id")) == job_id)
    ][:5]
    return {
        "url": url.strip(),
        "run_id": int(run_id),
        "conclusion": run.get("conclusion"),
        "head_sha": run.get("head_sha"),
        "failed_jobs": [
            {
                "name": job.get("name"),
                "failed_steps": [
                    step.get("name")
                    for step in job.get("steps", [])
                    if step.get("conclusion") == "failure"
                ],
                "log_excerpt": _job_log_tail(github, repository, job.get("id")),
            }
            for job in failed
        ],
    }


def _prepare(args, scratch):
    github = _github()
    proposal.require(
        args.repository == os.environ.get("GITHUB_REPOSITORY"),
        "requested repository differs from trusted workflow repository",
    )
    proposal.require(
        _git(_env(scratch / "home"), args.repo, "rev-parse", "HEAD").strip()
        == args.default_sha,
        "requested default revision differs from trusted checkout HEAD",
    )
    event = _read(args.event) if args.event else None
    context = publish.prepare_context(github, args.repository, args.default_sha, event)
    context["bot_login"] = github.bot_login
    _write(args.output / "context.json", context)
    if context["status"] in {"ignored", "duplicate", "blocked", "failed"}:
        return _result("prepare", context["status"], context["reason"])
    if args.pack_run_url:
        context["pack_failure"] = _pack_failure(
            github,
            args.repository,
            args.pack_run_url,
        )
    env = _env(scratch / "home")
    frozen = scratch / "frozen"
    _clone(args.repo, args.default_sha, frozen, env)
    releases, errors = _releases(PublicUpstream())
    pairs = _pair(releases.get(discovery.ASCEND, []))
    found = discovery.discover(frozen, releases, pairs)
    _write(args.output / "discovery.json", found)
    context["discovery"] = found
    # The whitelist is read from the frozen default checkout, never the candidate.
    context["prerelease_packages"] = discovery.prerelease_packages(frozen)
    _write(args.output / "context.json", context)
    candidates = _candidates(found)
    if context["status"] == "deferred":
        return _result(
            "prepare",
            "deferred",
            context["reason"],
            candidates=candidates,
            discovery=found,
        )
    needed = context["identity"]["mode"] == "revise" or any(
        c["status"] == "needs_update" for c in found
    )
    status = (
        "ready"
        if needed
        else "failed"
        if any(c["status"] == "failed" for c in found)
        else "blocked"
        if any(c["status"] == "blocked" for c in found)
        else "unchanged"
    )
    if needed:
        _ensure_head(args.repo, context, env)
    return _result(
        "prepare",
        status,
        "Discovery inspected all subscriptions.",
        candidates=candidates,
        ready=needed,
        discovery=found,
        upstream_errors=errors,
    )


def _context(bundle: Path, repo: Path) -> dict:
    context = _read(bundle / "context.json")
    proposal.validate_identity(context["identity"])
    proposal.require(
        context.get("status") == "ready",
        "bundle does not authorize research or publication",
    )
    proposal.require(
        isinstance(context.get("bot_login"), str)
        and context["bot_login"].endswith("[bot]"),
        "bundle lacks frozen App identity",
    )
    proposal.require(
        context["identity"]["repository"] == os.environ.get("GITHUB_REPOSITORY"),
        "bundle repository differs from trusted workflow repository",
    )
    with tempfile.TemporaryDirectory(prefix="runner-identity-") as temporary:
        head = _git(_env(Path(temporary)), repo, "rev-parse", "HEAD").strip()
    proposal.require(
        head == context["identity"]["default_sha"],
        "bundle default revision differs from trusted checkout HEAD",
    )
    return context


def _agent_workspace(repo, identity, target, env):
    """Clone the frozen head and strip candidate-controlled startup configuration."""
    _clone(repo, identity["head_sha"], target, env)
    # Candidate configuration cannot control the agent's startup or policy.
    for path in (
        ".qwen",
        ".env",
        ".mcp.json",
        ".claude",
        ".agents",
        "tools",
        "AGENTS.md",
    ):
        selected = target / path
        if selected.is_dir() and not selected.is_symlink():
            shutil.rmtree(selected)
        else:
            selected.unlink(missing_ok=True)
    _git(
        env,
        target,
        "checkout",
        identity["default_sha"],
        "--",
        "AGENTS.md",
        ".agents",
        ".claude/skills",
        "tools",
    )
    return target


def _checker_seed(workspace: Path, files: dict) -> None:
    """Trusted checker copy and per-stage seed; a dot-dir repair sessions keep."""
    target = workspace / ".autosync"
    shutil.copytree(
        Path(__file__).parent,
        target / "tools" / "auto_sync",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )
    seed = target / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        _write(seed / name, data)
    # Keep git add -A from sweeping the checker into a candidate patch.
    exclude = workspace / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.touch()
    if ".autosync" not in exclude.read_text(encoding="utf-8").splitlines():
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write(".autosync\n")


def _repair_prompt(
    phase: str,
    schema: dict,
    failed_reply: str,
    error: str,
    evidence_keys=(),
) -> str:
    """Ask one fresh bounded session to correct a rejected final reply."""
    payload = {
        "schema": schema,
        "validation_error": error,
        "failed_reply": failed_reply,
    }
    guidance = ""
    if evidence_keys:
        # A fresh session cannot see the original prompt; name the valid keys.
        payload["supplied_evidence_keys"] = sorted(evidence_keys)
        guidance = (
            " An evidence entry rejected by the error must be replaced with the"
            " matching key from supplied_evidence_keys."
        )
    correction = (
        "This is a pure format and field correction: do not research again, do not edit any "
        "file, and do not access the network for new investigation."
    )
    if error.startswith("invalid JSON") and _truncated_reply(failed_reply):
        # The model stopped at its single-message output ceiling; a repair
        # can succeed only with a smaller object, never a verbatim retry.
        guidance += (
            " The rejected reply was cut off mid-structure at the model output"
            " ceiling; return the complete object with concise reason and report text."
        )
    elif error.startswith("invalid JSON"):
        guidance += (
            " The rejected reply carries text outside its JSON object; return that same"
            " object and drop every other character."
        )
    if phase == "proposal":
        # A patch rejection is only correctable in the reused workspace.
        correction = (
            "This is a pure format and field correction: do not research again and do not "
            "access the network for new investigation. When the error rejects a group's patch, "
            "rewrite the patch files referenced by patch_file entries in the reused workspace "
            "and keep those references; do not edit any other file."
        )
    return _prompt(
        "repair",
        phase=phase,
        correction=correction,
        guidance=guidance,
        payload=json.dumps(payload),
    )


def _truncated_reply(failed_reply: str) -> bool:
    """A reply cut at the output ceiling ends mid-structure, never wrapped in prose."""
    stripped = failed_reply.rstrip()
    if not stripped:
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError as exc:
        return exc.pos == len(stripped) or exc.msg.startswith("Unterminated string")
    return False


def _check_dispositions(base: Path, work: Path, group: dict) -> None:
    """
    Mirror validation's disposition checks where a repair session can correct them.

    The group diff must express every declared patch decision, and every
    existing patch of an affected component needs a declared disposition;
    validation rejects the same mismatches where no repair exists.
    """
    decisions = {d["path"]: d for row in group["rows"] for d in row["patches"]}
    touched = set()
    for match in re.finditer(
        r"^diff --git a/(\S+) b/(\S+)$",
        group["patch"],
        re.MULTILINE,
    ):
        touched.update(path for path in match.groups() if path.endswith(".patch"))
    for path, decision in decisions.items():
        disposition = decision["disposition"]
        exists = (work / path).exists()
        if disposition == "remove":
            proposal.require(
                not exists,
                f"group {group['id']} declares remove but the patch still exists: {path}",
            )
        else:
            proposal.require(
                exists,
                f"group {group['id']} declares {disposition} but the declared patch is missing: {path}",
            )
        if path in touched:
            existed = (base / path).exists()
            proposal.require(
                (disposition == "add" and not existed and exists)
                or (disposition == "adapt" and existed and exists)
                or (disposition == "remove" and existed and not exists),
                f"group {group['id']} patch changes disagree with the {disposition} disposition: {path}",
            )
    for path in sorted(touched):
        proposal.require(
            path in decisions,
            f"group {group['id']} changed patch lacks a disposition: {path}",
        )
    for row in group["rows"]:
        components = {row["service"]}
        if row["service"] == "vllm":
            components |= {"vllm_ascend", "vllm_omni"}
        for component in sorted(components):
            directory = base / "pack" / row["backend"] / "patches" / component
            if not directory.is_dir():
                continue
            for patch in sorted(directory.rglob("*.patch")):
                path = patch.relative_to(base).as_posix()
                proposal.require(
                    path in decisions,
                    f"group {group['id']} affected existing patch lacks a disposition: {path}",
                )


def _check_patch_versions(data: dict) -> None:
    # Mirror the trusted acquisition coverage rule where a repair session can
    # still correct it: every kept patch on a ready group must list the
    # version of the component it applies to — the selected plugin for Ascend
    # patches, otherwise the selected engine.
    for group in data["groups"]:
        if group["status"] != "ready":
            continue
        for row in group["rows"]:
            for patch in row["patches"]:
                if patch["disposition"] == "remove":
                    continue
                parts = Path(patch["path"]).parts
                applicable = row["engine_version"]
                if len(parts) > 4 and parts[3] == "vllm_ascend":
                    applicable = row["plugin_version"]
                proposal.require(
                    applicable is not None
                    and discovery.version(applicable)
                    in {discovery.version(v) for v in patch["versions"]},
                    f"group {group['id']} patch {patch['path']} versions "
                    f"{patch['versions']} do not cover the selected component "
                    f"version {applicable}",
                )


def _check_group_patches(
    repo: Path,
    identity: dict,
    data: dict,
    scratch: Path,
    env: dict,
) -> dict:
    """
    Apply every checkable ready group's patch to a fresh frozen-head clone.

    A malformed patch must fail here, where a repair session can correct
    it, instead of in the validation job where no repair exists. A ready
    group whose dependencies are not all ready is validated later instead.
    The --whitespace=error flag mirrors the downstream validation and
    publication applications, which reject whitespace-damaged patches.
    Dispositions are checked against the resulting tree for the same reason.
    """
    groups = {g["id"]: g for g in data["groups"]}
    ready = {g["id"] for g in data["groups"] if g["status"] == "ready"}
    checkable = set()
    changed = True
    while changed:
        changed = False
        for identifier in ready - checkable:
            if all(d in checkable for d in groups[identifier]["depends_on"]):
                checkable.add(identifier)
                changed = True
    if not checkable:
        return data
    work = scratch / "patch-check"
    shutil.rmtree(work, ignore_errors=True)
    _clone(repo, identity["head_sha"], work, env)
    base = scratch / "patch-check-base"
    shutil.rmtree(base, ignore_errors=True)
    _clone(repo, identity["head_sha"], base, env)
    applied = set()
    while checkable - applied:
        progressed = False
        for identifier in sorted(checkable - applied):
            if not set(groups[identifier]["depends_on"]) <= applied:
                continue
            try:
                _git(
                    env,
                    work,
                    "apply",
                    "--whitespace=error",
                    "-",
                    text=groups[identifier]["patch"],
                )
            except proposal.ProposalError as exc:
                msg = (
                    f"group {identifier} patch does not apply to the frozen head: {exc}"
                )
                raise proposal.ProposalError(msg) from None
            applied.add(identifier)
            progressed = True
            _check_dispositions(base, work, groups[identifier])
        proposal.require(progressed, "group patch order is unresolvable")
    return data


def _strip_untrusted_config(workspace: Path) -> None:
    """Remove agent startup configuration without following hostile symlinks."""
    for config_path in agent.UNTRUSTED_STARTUP_CONFIG:
        parent = workspace
        hostile = False
        for part in Path(config_path).parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                # Unlink the hostile link itself; never traverse it.
                parent.unlink()
                hostile = True
                break
            if not parent.is_dir():
                hostile = True
                break
        if hostile:
            continue
        selected = workspace / config_path
        if selected.is_dir() and not selected.is_symlink():
            shutil.rmtree(selected)
        else:
            selected.unlink(missing_ok=True)


def _research(args, scratch):
    context = _context(args.bundle, args.repo)
    prepared = _read(args.bundle / "result.json")
    proposal.require(
        prepared["stage"] == "prepare" and prepared["ready"],
        "prepared result does not require research",
    )
    _write(args.output / "context.json", context)
    found = _read(args.bundle / "discovery.json")
    proposal.require(
        found == context["discovery"],
        "discovery differs from the original frozen context",
    )
    _write(args.output / "discovery.json", found)
    inputs = {
        "llm-" + key: os.environ.get(
            "AUTO_SYNC_LLM_" + key.upper().replace("-", "_"),
            "",
        )
        for key in LLM_INPUTS
    }
    limit = os.environ.get("AUTO_SYNC_MAX_SESSION_TOKENS", "").strip() or str(
        agent.MAX_SESSION_TOKENS,
    )
    if not re.fullmatch(r"[0-9]+", limit) or int(limit) <= 0:
        msg = "The session token limit must be a positive integer"
        raise model.ConfigurationError(msg)
    max_session_tokens = int(limit)
    rounds = os.environ.get("AUTO_SYNC_MAX_REPAIR_ROUNDS", "").strip() or str(
        agent.MAX_REPAIR_ROUNDS,
    )
    if not re.fullmatch(r"[0-9]+", rounds):
        msg = "The repair round limit must be a non-negative integer"
        raise model.ConfigurationError(msg)
    max_repair_rounds = int(rounds)
    config = model.normalize_inputs(inputs)
    github = _github()
    proposal.require(
        github.bot_login == context["bot_login"],
        "research App identity changed",
    )
    env = _env(scratch / "home")
    identity = context["identity"]
    permissions = _permissions(context)
    packages = _package_prereleases(context)
    releases, upstream_errors = _releases(PublicUpstream())
    _, evidence, source_errors = _selected_sources(
        PublicUpstream(),
        releases,
        found,
        scratch / "upstreams",
        env,
        permissions,
    )
    component_evidence, component_errors = _component_sources(
        PublicUpstream(),
        args.repo,
        identity["default_sha"],
        found,
        scratch / "upstreams",
        env,
    )
    evidence.update(component_evidence)
    source_errors.update(component_errors)
    shared = {
        "context": context,
        "discovery": found,
        "upstream_sources": evidence,
        "upstream_errors": upstream_errors,
        "source_errors": source_errors,
        "authorized_prereleases": sorted(permissions),
        "prerelease_packages": sorted(packages),
        "pack_failure": context.get("pack_failure"),
    }
    analysis_schema = {
        "schema_version": 1,
        "identity": identity,
        "candidates": [
            {
                "subscription": f"{b}/{s}",
                "status": "analyzed, blocked or unchanged; never ready",
                "reason": "Explain the result.",
                "engine_version": "discovered engine version or null",
                "plugin_version": "discovered plugin version or null",
                "source_revision": (
                    "exact commit of the candidate engine repository (vllm or sglang upstream) or null; "
                    "for a CANN vLLM pair use the vllm engine commit and record the "
                    "vllm-ascend plugin commit in findings or evidence"
                ),
                "evidence": [
                    "supplied evidence key, supplied path, repository-relative path, "
                    "or one bare https URL without appended annotations",
                ],
                "findings": "Measured compatibility facts with their evidence classification.",
                "patches": "Patch disposition review summary with exact-revision check results.",
                "unknowns": ["Specific missing facts; required for blocked."],
            }
            for b, s, _ in discovery.SUBSCRIPTIONS
        ],
    }
    analysis_prompt = _prompt(
        "analysis",
        max_session_turns=str(agent.MAX_SESSION_TURNS),
        max_tool_calls=str(agent.MAX_TOOL_CALLS),
        reserved_turns=str(agent.MAX_SESSION_TURNS // 4),
        payload=json.dumps({**shared, "schema": analysis_schema}),
    )
    schema = {
        "schema_version": 1,
        "identity": identity,
        "candidates": [
            {
                "subscription": f"{b}/{s}",
                "status": "blocked",
                "groups": [],
                "reason": "Explain the result.",
            }
            for b, s, _ in discovery.SUBSCRIPTIONS
        ],
        "groups": [],
    }
    tool_bin = Path(os.environ.get("AUTO_SYNC_TOOL_BIN", ""))
    proposal.require(
        bool(os.environ.get("AUTO_SYNC_TOOL_BIN")),
        "required pinned tool directory is missing",
    )
    mcp_servers = {
        **agent.github_mcp(
            tool_bin,
            os.environ.get("AUTO_SYNC_GITHUB_TOKEN", ""),
        ),
        **agent.deepwiki_mcp(),
    }
    agent_started = time.monotonic()
    phases = []
    reported_total = 0
    analysis = None

    def record(name: str, result, started: float) -> None:
        events = []
        for line in proposal.stream_lines(result.stdout):
            if not line.strip():
                continue
            try:
                events.append(proposal.load_json(line))
            except proposal.ProposalError:
                events.append({"type": "unparsed", "text": line})
        phases.append(
            {
                "name": name,
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "agent_seconds": round(time.monotonic() - started, 3),
                "reported_tokens": result.reported_tokens,
                "events": events,
                "stderr": result.stderr,
            },
        )

    def failed(result, reported: int) -> None:
        # The durable budget reason must survive the CLI's interruption error.
        if reported >= max_session_tokens:
            msg = (
                f"session token budget exceeded: {reported} reported tokens "
                f"reached the {max_session_tokens} limit"
            )
            raise proposal.ProposalError(msg)
        reason = result.stderr
        for line in reversed(proposal.stream_lines(result.stdout)):
            try:
                event = proposal.load_json(line)
            except proposal.ProposalError:
                continue
            if (
                isinstance(event, dict)
                and event.get("type") == "result"
                and event.get("is_error") is True
                and isinstance(event.get("error"), dict)
                and isinstance(event["error"].get("message"), str)
            ):
                reason = event["error"]["message"]
                break
        msg = f"agent process failed or timed out (exit {result.returncode}): {reason[-1000:]}"
        raise proposal.ProposalError(msg)

    def session(
        name: str,
        workspace: Path,
        prompt: str,
        *,
        budget: int,
        deadline: float | None = None,
    ):
        """Run one bounded stage session and account it against the shared budget."""
        nonlocal reported_total
        # A repair session reuses the previous session's workspace; strip any
        # startup configuration the model created so it can neither steer nor
        # block the fresh session's preflight.
        _strip_untrusted_config(workspace)
        started = time.monotonic()
        extra = {} if deadline is None else {"deadline": deadline}
        result = agent.run_agent(
            config,
            workspace=workspace,
            tool_bin=tool_bin,
            prompt=prompt,
            runtime_dir=scratch / f"runtime-{name}",
            max_session_tokens=budget,
            mcp_servers=mcp_servers,
            progress=lambda line: _print_progress(f"[{name}] {line}"),
            **extra,
        )
        record(name, result, started)
        reported_total += result.reported_tokens
        if result.returncode != 0 or result.timed_out:
            failed(result, reported_total)
        return result

    def research_phase(
        phase: str,
        workspace: Path,
        prompt: str,
        schema: dict,
        finalize,
        budget: int,
        deadline: float | None = None,
    ):
        """
        Run one stage, then bounded fresh repair sessions for rejected output.

        A malformed event stream or failed process is never repaired; a reply
        that parses but fails validation, or text that fails to parse, returns
        to a fresh session with the exact error until the rounds are exhausted.
        """
        result = session(phase, workspace, prompt, budget=budget, deadline=deadline)
        spent = result.reported_tokens
        last = ""
        for rounds in range(max_repair_rounds + 1):
            reply = proposal.final_reply_text(result)
            try:
                return finalize(proposal.parse_reply(reply)), spent
            except proposal.ProposalError as error:
                last = str(error)
            if rounds == max_repair_rounds:
                break
            deadline = agent.SESSION_DEADLINE - (time.monotonic() - agent_started)
            proposal.require(
                deadline > 0,
                f"research stage deadline exhausted by the {phase} stage",
            )
            proposal.require(
                reported_total < max_session_tokens,
                f"session token budget exhausted by the {phase} stage: "
                f"{reported_total} reported tokens reached the "
                f"{max_session_tokens} limit",
            )
            result = session(
                f"{phase}-repair-{rounds + 1}",
                workspace,
                _repair_prompt(
                    phase,
                    schema,
                    reply,
                    last,
                    evidence_keys=list(evidence) if phase == "analysis" else (),
                ),
                budget=max_session_tokens - reported_total,
                deadline=deadline,
            )
            spent += result.reported_tokens
        msg = f"{phase} repair rounds exhausted: {last}"
        raise proposal.ProposalError(msg)

    def finalize_proposal(data):
        # Inline referenced workspace patch files before semantic validation so
        # the final reply stays small enough for the model's output limit.
        bound = _bind_discovery(
            proposal.validate_proposal(
                assemble.assemble(data, proposal_workspace),
                identity,
                engine_prereleases=permissions,
                prerelease_packages=packages,
            ),
            context,
        )
        _check_patch_versions(bound)
        return _check_group_patches(args.repo, identity, bound, scratch, env)

    try:
        analysis_workspace = _agent_workspace(
            args.repo,
            identity,
            scratch / "workspace-analysis",
            env,
        )
        _checker_seed(
            analysis_workspace,
            {
                "identity.json": identity,
                "discovery.json": found,
                "evidence.json": evidence,
            },
        )
        analysis, reported = research_phase(
            "analysis",
            analysis_workspace,
            analysis_prompt,
            analysis_schema,
            lambda data: proposal.validate_analysis(
                data,
                identity,
                found=found,
                evidence=evidence,
            ),
            budget=max_session_tokens,
        )
        remaining = max_session_tokens - reported
        proposal.require(
            remaining > 0,
            f"session token budget exhausted by analysis: {reported} "
            f"reported tokens reached the {max_session_tokens} limit",
        )
        deadline = agent.SESSION_DEADLINE - (time.monotonic() - agent_started)
        proposal.require(
            deadline > 0,
            "research stage deadline exhausted by the analysis session",
        )
        proposal_prompt = _prompt(
            "proposal",
            max_session_turns=str(agent.MAX_SESSION_TURNS),
            max_tool_calls=str(agent.MAX_TOOL_CALLS),
            reserved_turns=str(agent.MAX_SESSION_TURNS // 4),
            payload=json.dumps({**shared, "analysis": analysis, "schema": schema}),
        )
        proposal_workspace = _agent_workspace(
            args.repo,
            identity,
            scratch / "workspace",
            env,
        )
        _checker_seed(
            proposal_workspace,
            {
                "identity.json": identity,
                "permissions.json": {
                    "engine_prereleases": [list(item) for item in sorted(permissions)],
                    "prerelease_packages": sorted(packages),
                },
            },
        )
        raw, _ = research_phase(
            "proposal",
            proposal_workspace,
            proposal_prompt,
            schema,
            finalize_proposal,
            budget=remaining,
            deadline=deadline,
        )
    finally:
        # Restore both input and output only after supervised children finish.
        _restore_bundle(
            args.bundle,
            {"context": context, "discovery": found, "result": prepared},
        )
        _restore_bundle(args.output, {"context": context, "discovery": found})
        if phases:
            _write(
                args.output / "diagnostics.json",
                {
                    "phases": phases,
                    "reported_tokens": sum(p["reported_tokens"] for p in phases),
                },
            )
        if analysis is not None:
            _write(args.output / "analysis.json", analysis)
    _write(args.output / "proposal.json", raw)

    def stage_sum(prefix: str, field: str):
        return sum(
            p[field]
            for p in phases
            if p["name"] == prefix or p["name"].startswith(prefix + "-")
        )

    return _result(
        "research",
        "ready",
        "Analysis and proposal sessions completed.",
        candidates=raw["candidates"],
        durations={
            "analysis_seconds": round(stage_sum("analysis", "agent_seconds"), 3),
            "proposal_seconds": round(stage_sum("proposal", "agent_seconds"), 3),
        },
        usage={
            "analysis": stage_sum("analysis", "reported_tokens"),
            "proposal": stage_sum("proposal", "reported_tokens"),
            "reported": sum(p["reported_tokens"] for p in phases),
        },
    )


def _validate(args, scratch):
    context = _context(args.bundle, args.repo)
    _write(args.output / "context.json", context)
    data, sources, pairs = _acquire_candidate(
        _read(args.bundle / "proposal.json"),
        context,
        scratch,
    )
    _ensure_head(args.repo, context, _env(scratch / "home"))
    checks_started = time.monotonic()
    checked = checks.validate_candidate(
        args.repo,
        data,
        context["identity"],
        sources=sources,
        ascend_pairs=pairs,
        engine_prereleases=_permissions(context),
        prerelease_packages=_package_prereleases(context),
    )
    _write(args.output / "artifact.json", checked)
    candidates = checked["candidates"]
    status = (
        "ready"
        if checked["patch"]
        else "failed"
        if any(c["status"] == "failed" for c in candidates)
        else "blocked"
        if any(c["status"] == "blocked" for c in candidates)
        else "unchanged"
    )
    return _result(
        "validate",
        status,
        "Trusted acquisition and credential-free static checks completed.",
        candidates=candidates,
        publishable=bool(checked["patch"]) or context["identity"]["mode"] == "revise",
        durations={"checks_seconds": round(time.monotonic() - checks_started, 3)},
    )


def _publish(args, scratch):
    context = _context(args.bundle, args.repo)
    github = _github()
    proposal.require(
        github.bot_login == context["bot_login"],
        "publication App identity differs from frozen research identity",
    )
    artifact = _read(args.bundle / "artifact.json")
    _ensure_head(args.repo, context, _env(scratch / "home"))
    raw = checks.verify_artifact(
        artifact,
        context["identity"],
        engine_prereleases=_permissions(context),
        prerelease_packages=_package_prereleases(context),
    )
    data, sources, pairs = _acquire_candidate(raw, context, scratch)
    proposal.require(
        data == raw,
        "publication acquisition changed; preserve the original bundle and recompute before writes",
    )
    result = publish.publish(
        github,
        args.repo,
        context,
        artifact,
        sources=sources,
        ascend_pairs=pairs,
        engine_prereleases=_permissions(context),
        prerelease_packages=_package_prereleases(context),
    )
    fields = {
        k: result[k] for k in ("pr_number", "commit_sha", "revalidation") if k in result
    }
    return _result(
        "publish",
        result["status"],
        result["reason"],
        candidates=(result.get("checked") or artifact)["candidates"],
        **fields,
    )


def _secrets():
    secrets = []
    for key in ("AUTO_SYNC_GITHUB_TOKEN", "AUTO_SYNC_LLM_AUTH_TOKEN"):
        secrets.extend(
            v.strip() for v in os.environ.get(key, "").split(",") if v.strip()
        )
    for value in os.environ.get("AUTO_SYNC_LLM_EXTRA_HEADERS", "").split(","):
        if "=" in value:
            secrets.append(value.split("=", 1)[1].strip())
    return [v for v in secrets if v]


def _redact(value, secrets):
    return proposal.redact(value, proposal.ordered_secrets(secrets))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "research", "validate", "publish"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--repository", required=True)
            command.add_argument("--default-sha", required=True)
            command.add_argument("--event", type=Path)
            command.add_argument("--pack-run-url", default="")
        else:
            command.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    result_path = (
        args.output if args.command == "publish" else args.output / "result.json"
    )
    secrets = _secrets()
    writable = False
    try:
        proposal.require(
            not args.output.resolve().is_relative_to(args.repo.resolve()),
            "stage output must remain outside the checkout",
        )
        if args.command != "prepare":
            proposal.require(
                not args.output.resolve().is_relative_to(args.bundle.resolve()),
                "stage output must not overwrite the original bundle",
            )
        if args.command != "publish":
            args.output.mkdir(parents=True, exist_ok=False)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
        writable = True
        with tempfile.TemporaryDirectory(prefix="runner-auto-sync-") as temporary:
            result = globals()["_" + args.command](args, Path(temporary))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        candidates = None
        if args.command == "research" and (args.bundle / "discovery.json").is_file():
            with contextlib.suppress(ValueError, OSError, KeyError, TypeError):
                candidates = _candidates(
                    _read(args.bundle / "discovery.json"),
                    failed=True,
                    reason=str(exc),
                )
        result = _result(args.command, "failed", str(exc), candidates=candidates)
    result["durations"][args.command + "_seconds"] = round(
        time.monotonic() - started,
        3,
    )
    result = _redact(result, secrets)
    if writable and result_path.parent.is_dir():
        # Redact all transport files; never persist model/GitHub credentials.
        if args.command != "publish":
            for path in args.output.glob("*.json"):
                _write(path, _redact(_read(path), secrets))
        _write(result_path, result)
    print(json.dumps(result, ensure_ascii=True))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
