"""
Collect final-image dependencies and validate their build receipts.

CLI: ``collect --invocation I --build B --mapping M --output R`` or
``validate --invocation I --builds B --mapping M --receipts R... --output V``.
All files are JSON. Invocation fields are workflow_run, source_revision,
matrix_digest and mapping_digest. Digests use content_digest on parsed JSON;
object key order is irrelevant, but list order (including aliases) is preserved.
Build fields are job, attempt, backend, service, image, platform and image_digest.
The caller supplies these records from trusted build output, never from receipts.

Partial reruns retain the frozen invocation and select the authoritative attempt
for each build. Replace its old receipt before validation; duplicates are rejected.
Successful receipts contain raw distributions. Use fold_dependencies only after
validating the complete set. Explicitly disabled collection has status unknown
and carries no distributions. Failed collection writes a failure receipt and exits 1.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import platform as host_platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
PLATFORM_RE = re.compile(r"linux/(amd64|arm64)(/v[1-9][0-9]*)?\Z")
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
INVOCATION_FIELDS = {
    "workflow_run",
    "source_revision",
    "matrix_digest",
    "mapping_digest",
}
BUILD_FIELDS = {
    "job",
    "attempt",
    "backend",
    "service",
    "image",
    "platform",
    "image_digest",
}

# Compare Python environments, not executable realpaths: virtual environments
# commonly symlink the same binary while exposing different distribution metadata.
SELECT_INTERPRETER = r"""
set -eu
selected=
identity=
check_python() {
    candidate=$1
    if [ ! -x "$candidate" ]; then
        echo "service interpreter unavailable: $candidate" >&2
        exit 1
    fi
    found=$("$candidate" -B -c 'import json,sys,sysconfig; print(json.dumps([sys.prefix,sysconfig.get_path("purelib"),sysconfig.get_path("platlib")]))' </dev/null)
    if [ -n "$identity" ] && [ "$identity" != "$found" ]; then
        echo "ambiguous service Python environments: $selected and $candidate" >&2
        exit 1
    fi
    if [ -z "$selected" ]; then selected=$candidate; identity=$found; fi
}
if [ -n "${VIRTUAL_ENV:-}" ]; then check_python "$VIRTUAL_ENV/bin/python"; fi
if [ -n "$1" ]; then check_python "$1/bin/python"; fi
for name in python python3; do
    candidate=$(command -v "$name" || true)
    if [ -n "$candidate" ]; then check_python "$candidate"; fi
done
if [ -z "$selected" ]; then
    echo "service interpreter unavailable on PATH" >&2
    exit 1
fi
exec "$selected" -B -c "$2"
"""


def content_digest(value: object) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(serialized.encode()).hexdigest()


def validate_mapping(mapping: dict) -> None:
    if not isinstance(mapping, dict) or not mapping:
        message = "dependency mapping must be a nonempty object"
        raise ValueError(message)
    seen = set()
    for name, aliases in mapping.items():
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            message = "invalid dependency name in mapping"
            raise ValueError(message)
        if not isinstance(aliases, list) or not aliases:
            message = "dependency aliases must be nonempty ordered lists"
            raise ValueError(message)
        for alias in aliases:
            if (
                not isinstance(alias, str)
                or not NAME_RE.fullmatch(alias)
                or alias in seen
            ):
                message = (
                    "dependency mapping has invalid or duplicate distribution aliases"
                )
                raise ValueError(message)
            seen.add(alias)


def validate_invocation(invocation: dict, mapping: dict) -> None:
    validate_mapping(mapping)
    if not isinstance(invocation, dict) or set(invocation) != INVOCATION_FIELDS:
        message = "invalid invocation fields"
        raise ValueError(message)
    if any(
        not isinstance(value, str) or not value.strip() for value in invocation.values()
    ):
        message = "invocation identities must be nonempty strings"
        raise ValueError(message)
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", invocation["source_revision"]):
        message = "source_revision must be a full commit identity"
        raise ValueError(message)
    if not DIGEST_RE.fullmatch(invocation["matrix_digest"]):
        message = "invalid selected matrix digest"
        raise ValueError(message)
    if invocation["mapping_digest"] != content_digest(mapping):
        message = "dependency mapping digest mismatch"
        raise ValueError(message)


def validate_build(build: dict) -> None:
    if not isinstance(build, dict) or set(build) != BUILD_FIELDS:
        message = "invalid build fields"
        raise ValueError(message)
    if type(build["attempt"]) is not int or build["attempt"] < 1:
        message = "build attempt must be a positive integer"
        raise ValueError(message)
    for field in BUILD_FIELDS - {"attempt"}:
        if not isinstance(build[field], str) or not build[field].strip():
            message = f"invalid build {field}"
            raise ValueError(message)
    if not DIGEST_RE.fullmatch(build["image_digest"]):
        message = "invalid final image digest"
        raise ValueError(message)
    if not PLATFORM_RE.fullmatch(build["platform"]):
        message = "unsupported full Linux platform"
        raise ValueError(message)
    if not re.fullmatch(r"[a-z0-9][a-zA-Z0-9._:/-]*", build["image"]):
        message = "image must be a repository or tagged repository reference"
        raise ValueError(message)


def validate_distributions(distributions: dict, mapping: dict) -> None:
    allowed = {alias for aliases in mapping.values() for alias in aliases}
    if not isinstance(distributions, dict):
        message = "successful collection requires a distributions object"
        raise ValueError(message)  # noqa: TRY004 - Malformed JSON is a validation error.
    for name, version in distributions.items():
        if name not in allowed or not isinstance(version, str) or not version.strip():
            message = "invalid collected distribution name or version"
            raise ValueError(message)


def fold_dependencies(distributions: dict, mapping: dict) -> dict[str, str]:
    validate_mapping(mapping)
    validate_distributions(distributions, mapping)
    folded = {}
    for name, aliases in mapping.items():
        for alias in aliases:
            if alias in distributions:
                folded[name] = distributions[alias]
                break
    return folded


def probe_command(backend: str, service: str) -> list[str]:
    known_venv = "/opt/venv" if (backend, service) == ("rocm", "sglang") else ""
    source = (
        Path(__file__).with_name("probe_dependencies.py").read_text(encoding="utf-8")
    )
    return ["/bin/sh", "-c", SELECT_INTERPRETER, "probe", known_venv, source]


def run_command(
    command: list[str],
    *,
    timeout: float,
    input_text=None,
    env=None,
) -> str:
    process = subprocess.Popen(  # noqa: S603 - Fixed programs use argument arrays, never shell input.
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    try:
        try:
            stdout, stderr = process.communicate(input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            # Escaped descendants can hold pipes open. Reap only the direct child
            # with a finite wait, preserving the original timeout and its output.
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode,
                command,
                stdout,
                stderr,
            )
        return stdout
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            with contextlib.suppress(BrokenPipeError):
                stream.close()


def execution_error(error: Exception) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        return f"command failed (exit {error.returncode}): {error.stderr}"
    if isinstance(error, subprocess.TimeoutExpired):
        return "collection timeout exceeded"
    return str(error)


def run_image(image_ref, platform, backend, service, mapping, timeout) -> dict:
    architecture = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        host_platform.machine().lower(),
    )
    if host_platform.system() != "Linux" or platform.split("/")[1] != architecture:
        message = "collection requires a native Linux runner for the target platform"
        raise ValueError(message)
    deadline = time.monotonic() + timeout

    def execute(command, input_text=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        return run_command(command, input_text=input_text, timeout=remaining)

    execute(["docker", "pull", "--platform", platform, image_ref])
    images = json.loads(execute(["docker", "image", "inspect", image_ref]))
    if (
        not isinstance(images, list)
        or len(images) != 1
        or not isinstance(images[0], dict)
    ):
        message = "image inspection did not return exactly one image"
        raise ValueError(message)
    image = images[0]
    actual = "/".join(str(image.get(key, "")) for key in ("Os", "Architecture"))
    if image.get("Variant"):
        actual += "/" + image["Variant"]
    default_variants = {
        "linux/arm64/v8": "linux/arm64",
        "linux/amd64/v1": "linux/amd64",
    }
    if default_variants.get(actual, actual) != default_variants.get(platform, platform):
        message = f"image platform mismatch: expected {platform}, got {actual}"
        raise ValueError(message)
    name = "runner-dependencies-" + uuid.uuid4().hex
    probe = probe_command(backend, service)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--platform",
        platform,
        "--network",
        "none",
        "--entrypoint",
        probe[0],
        "-i",
        image_ref,
        *probe[1:],
    ]
    try:
        return json.loads(execute(command, json.dumps(mapping)))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Killing the Docker client does not stop its daemon-owned container.
        # Force removal has a separate finite budget, including on timeout.
        try:
            run_command(["docker", "rm", "--force", name], timeout=15)
        except (OSError, subprocess.SubprocessError) as cleanup_error:
            message = f"{execution_error(error)}; container cleanup failed: {execution_error(cleanup_error)}"
            raise RuntimeError(message) from cleanup_error
        raise


def collect(invocation, build, mapping, *, timeout=300, disabled=False) -> dict:
    validate_invocation(invocation, mapping)
    validate_build(build)
    if (
        not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        message = "collection timeout must be finite and positive"
        raise ValueError(message)
    receipt = {
        "schema_version": 1,
        "invocation": copy.deepcopy(invocation),
        "build": copy.deepcopy(build),
        "status": "unknown",
    }
    if disabled:
        return receipt
    # Strip only the final component's tag, preserving registry port numbers.
    repository = build["image"]
    if ":" in repository.rsplit("/", 1)[-1]:
        repository = repository.rsplit(":", 1)[0]
    try:
        result = run_image(
            repository + "@" + build["image_digest"],
            build["platform"],
            build["backend"],
            build["service"],
            mapping,
            timeout,
        )
        candidate = {**receipt, "status": "succeeded", **result}
        validate_receipts(invocation, [build], mapping, [candidate])
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        return {**receipt, "status": "failed", "error": execution_error(error)}
    else:
        return candidate


def validate_receipts(
    invocation,
    builds,
    mapping,
    receipts,
    *,
    allow_unknown=False,
) -> list[dict]:
    """Validate against independently retained build outputs, in matrix order."""
    validate_invocation(invocation, mapping)
    if not isinstance(builds, list) or not builds:
        message = "expected builds must be a nonempty list"
        raise ValueError(message)
    expected = {}
    for build in builds:
        validate_build(build)
        if build["job"] in expected:
            message = "duplicate expected build job"
            raise ValueError(message)
        expected[build["job"]] = build
    if not isinstance(receipts, list):
        message = "receipts must be a list"
        raise ValueError(message)  # noqa: TRY004 - Malformed JSON is a validation error.
    found = {}
    for receipt in receipts:
        if (
            not isinstance(receipt, dict)
            or type(receipt.get("schema_version")) is not int
            or receipt["schema_version"] != 1
        ):
            message = "invalid receipt schema"
            raise ValueError(message)
        if receipt.get("invocation") != invocation:
            message = "stale receipt invocation"
            raise ValueError(message)
        build = receipt.get("build")
        validate_build(build)
        job = build["job"]
        if job not in expected or expected[job] != build:
            message = "unexpected or stale receipt build identity"
            raise ValueError(message)
        if job in found:
            message = "duplicate collection receipt"
            raise ValueError(message)
        status = receipt.get("status")
        if status == "succeeded":
            validate_distributions(receipt.get("distributions"), mapping)
            for field in ("interpreter", "prefix"):
                if not isinstance(receipt.get(field), str) or not receipt[
                    field
                ].startswith("/"):
                    message = f"missing service {field} in receipt"
                    raise ValueError(message)
            if "error" in receipt:
                message = "successful receipt contains a failure"
                raise ValueError(message)
        elif (
            status != "unknown"
            or not allow_unknown
            or "distributions" in receipt
            or "error" in receipt
        ):
            message = f"collection is {status}; no valid dependency result"
            raise ValueError(message)
        found[job] = receipt
    if set(found) != set(expected):
        message = "missing collection receipts"
        raise ValueError(message)
    return [found[build["job"]] for build in builds]


def write_json(path: Path, value: object) -> None:
    """Replace a complete JSON result only after validation."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(value, output, sort_keys=True)
            output.write("\n")
            output.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--build", type=Path, required=True)
    collect_parser.add_argument("--timeout", type=float, default=300)
    collect_parser.add_argument("--disabled", action="store_true")
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--builds", type=Path, required=True)
    validate_parser.add_argument("--receipts", type=Path, nargs="+", required=True)
    validate_parser.add_argument("--allow-unknown", action="store_true")
    for subparser in (collect_parser, validate_parser):
        subparser.add_argument("--invocation", type=Path, required=True)
        subparser.add_argument("--mapping", type=Path, required=True)
        subparser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        invocation, mapping = read(args.invocation), read(args.mapping)
        if args.command == "collect":
            result = collect(
                invocation,
                read(args.build),
                mapping,
                timeout=args.timeout,
                disabled=args.disabled,
            )
            write_json(args.output, result)
            return int(result["status"] == "failed")
        result = validate_receipts(
            invocation,
            read(args.builds),
            mapping,
            [read(path) for path in args.receipts],
            allow_unknown=args.allow_unknown,
        )
        write_json(args.output, result)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
