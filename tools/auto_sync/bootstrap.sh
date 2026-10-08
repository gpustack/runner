#!/usr/bin/env bash
# Install fixed artifacts into a dedicated prefix. Never install global packages.
set -euo pipefail
exec python3 - "$0" "$@" <<'PY'
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--prefix", type=Path, required=True)
parser.add_argument("--verify", action="store_true", help="Validate only; never download or repair")
parser.add_argument("--cache-key", action="store_true", help="Print the installation identity and exit")
script = Path(sys.argv[1]).resolve()
args = parser.parse_args(sys.argv[2:])
manifest_path = script.with_name("tool-versions.json")
manifest = json.loads(manifest_path.read_text())
arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64"}.get(platform.machine())
system = platform.system().lower()
identity = f"{system}-{arch}"
image = os.environ.get("ImageOS") or (platform.platform() if system != "linux" else Path("/etc/os-release").read_text())
key = "auto-sync-" + hashlib.sha256(manifest_path.read_bytes() + script.read_bytes() + identity.encode() + image.encode()).hexdigest()
if args.cache_key:
    print(key)
    sys.exit(0)
prefix = args.prefix.expanduser().resolve()
if prefix == Path.home() or prefix == Path("/") or prefix == script.parents[2] or prefix.is_relative_to(script.parents[2]):
    sys.exit("bootstrap: prefix must be a dedicated directory outside the checkout")
started = time.monotonic()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("installation symlink escapes prefix")
            result[str(path.relative_to(root))] = {"link": os.readlink(path)}
        elif path.is_file() and path.name != ".receipt.json":
            result[str(path.relative_to(root))] = {"sha256": sha(path), "mode": path.stat().st_mode & 0o777}
    return result


def clean_env(root, home):
    return {"HOME": str(home), "PATH": str(root / "bin") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "CI": "1", "QWEN_CODE_SKIP_UPDATE_CHECK_ONCE": "1"}


def versions(root):
    with tempfile.TemporaryDirectory(prefix="auto-sync-tool-check-") as directory:
        env = clean_env(root, directory)
        for name, tool in manifest["tools"].items():
            result = subprocess.run([str(root / "bin" / name), *tool["version_args"]], env=env, cwd=directory, capture_output=True, text=True, timeout=30, check=True)
            if not re.search(r"(?<![\d.])v?" + re.escape(tool["version"]) + r"(?![\d.])", result.stdout + result.stderr):
                raise ValueError(f"{name} version mismatch")


def verify(root):
    receipt = json.loads((root / ".receipt.json").read_text())
    if receipt["cache_key"] != key or receipt["files"] != inventory(root):
        raise ValueError("cache identity or installed contents mismatch")
    for name, tool in manifest["tools"].items():
        artifact = tool["artifacts"].get(identity, tool["artifacts"].get("all"))
        if not artifact or sha(root / "archives" / (name + ".tgz")) != artifact["sha256"]:
            raise ValueError("artifact checksum mismatch")
    versions(root)


try:
    verify(prefix)
    hit = True
except (OSError, ValueError, KeyError, subprocess.SubprocessError):
    if args.verify:
        sys.exit("bootstrap: missing, corrupt, or incompatible cache")
    hit = False
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="auto-sync-install-", dir=prefix.parent) as directory:
        root = Path(directory)
        (root / "bin").mkdir()
        (root / "archives").mkdir()
        for name, tool in manifest["tools"].items():
            artifact = tool["artifacts"].get(identity, tool["artifacts"].get("all"))
            if artifact is None:
                sys.exit(f"bootstrap: unsupported platform {identity}")
            archive = root / "archives" / (name + ".tgz")
            subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--proto", "=https", "--tlsv1.2", "--connect-timeout", "15", "--max-time", "180", "--retry", "2", "--retry-max-time", "240", artifact["url"], "--output", str(archive)], check=True, timeout=300)
            if sha(archive) != artifact["sha256"]:
                sys.exit(f"bootstrap: {name} checksum mismatch")
            target = root / name
            target.mkdir()
            # Validate all archive paths before extraction, including links.
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    member_path = target / member.name
                    if not member_path.resolve().is_relative_to(target):
                        raise ValueError("archive path escapes installation")
                    if member.isdev() or member.isfifo():
                        raise ValueError("unsupported archive member")
                    if member.issym() or member.islnk():
                        link = (member_path.parent if member.issym() else target) / member.linkname
                        if not link.resolve().is_relative_to(target):
                            raise ValueError("archive link escapes installation")
            subprocess.run(["tar", "-xzf", str(archive), "-C", str(target), f"--strip-components={artifact['strip']}"], check=True, timeout=60)
            if name == "node":
                (root / "bin" / name).symlink_to("../node/bin/node")
            elif name == "qwen":
                launcher = root / "bin" / name
                launcher.write_text('#!/bin/sh\nexec "$(dirname "$0")/node" "$(dirname "$0")/../qwen/cli-entry.js" "$@"\n')
                launcher.chmod(0o755)
                for binary in target.glob("vendor/ripgrep/*/rg"):
                    binary.chmod(0o755)
            else:
                binary = next(path for path in target.rglob(name) if path.is_file())
                (root / "bin" / name).symlink_to("../" + str(binary.relative_to(root)))
        versions(root)
        (root / ".receipt.json").write_text(json.dumps({"cache_key": key, "files": inventory(root)}, sort_keys=True) + "\n")
        # Only replace this installer's own prefix. Never delete arbitrary files.
        if prefix.exists():
            if not (prefix / ".receipt.json").is_file():
                sys.exit("bootstrap: refusing to replace a directory without an installation receipt")
            shutil.rmtree(prefix)
        shutil.move(str(root), str(prefix))
    verify(prefix)

# These interfaces are supplied by the runner, not silently replaced here.
for command in (["git", "--version"], ["bash", "-c", "[[ ok == ok ]]"], ["jq", "-en", '.a = 1 | .a == 1'], ["yq", "eval", "-n", '.a = 1 | .a']):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, timeout=15)
print(json.dumps({"bin": str(prefix / "bin"), "prefix": str(prefix), "cache_key": key, "cache_hit": hit, "duration_seconds": round(time.monotonic() - started, 3)}))
PY
