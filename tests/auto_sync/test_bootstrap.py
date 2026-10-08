"""Run the real installer with small local archives and no network access."""

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def archive(path, filename, text):
    with tarfile.open(path, "w:gz") as bundle:
        item = tarfile.TarInfo(filename)
        payload = text.encode()
        item.size = len(payload)
        item.mode = 0o755
        bundle.addfile(item, io.BytesIO(payload))


@pytest.fixture
def installer(tmp_path):
    source = tmp_path / "checkout/tools/auto_sync"
    source.mkdir(parents=True)
    script = source / "bootstrap.sh"
    shutil.copy(ROOT / "tools/auto_sync/bootstrap.sh", script)
    manifest = json.loads((ROOT / "tools/auto_sync/tool-versions.json").read_text())
    archives = tmp_path / "archives"
    archives.mkdir()
    for name, tool in manifest["tools"].items():
        artifact_path = archives / (name + ".tgz")
        filename = name
        body = f"#!/bin/sh\nprintf '%s\\n' '{tool['version']}'\n"
        if name == "node":
            filename = "bin/node"
            body = (
                f"#!/bin/sh\nif [ \"$1\" = --version ]; then printf '%s\\n' 'v{tool['version']}'; "
                'else exec /bin/sh "$@"; fi\n'
            )
        elif name == "qwen":
            filename = "cli-entry.js"
        archive(artifact_path, filename, body)
        tool["artifacts"] = {
            "all": {
                "url": "https://fixture.invalid/" + artifact_path.name,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "strip": 0,
            },
        }
    manifest_path = source / "tool-versions.json"
    manifest_path.write_text(json.dumps(manifest))
    fake_bin = tmp_path / "runner-bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import os, shutil, sys\n"
        "from pathlib import Path\n"
        "url = next(arg for arg in sys.argv if arg.startswith('https://fixture.invalid/'))\n"
        "target = sys.argv[sys.argv.index('--output') + 1]\n"
        "shutil.copyfile(Path(os.environ['FIXTURE_ARCHIVES']) / url.rsplit('/', 1)[1], target)\n"
        "with open(os.environ['FIXTURE_DOWNLOADS'], 'a') as log: log.write(url + '\\n')\n",
    )
    curl.chmod(0o755)
    downloads = tmp_path / "downloads.txt"
    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "FIXTURE_ARCHIVES": str(archives),
        "FIXTURE_DOWNLOADS": str(downloads),
        "ImageOS": "fixture-image",
    }
    return {
        "script": script,
        "manifest": manifest_path,
        "prefix": tmp_path / "installed",
        "downloads": downloads,
        "env": env,
    }


def run(installer, *arguments):
    bash = shutil.which("bash")
    assert bash
    return subprocess.run(  # noqa: S603 - fixed installer and controlled offline fixtures.
        [
            bash,
            str(installer["script"]),
            "--prefix",
            str(installer["prefix"]),
            *arguments,
        ],
        env=installer["env"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def success(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_cold_install_and_exact_verified_cache(installer):
    cold = success(run(installer))
    assert cold["cache_hit"] is False
    assert Path(cold["bin"]).is_dir()
    expected = set(json.loads(installer["manifest"].read_text())["tools"])
    assert {path.name for path in Path(cold["bin"]).iterdir()} == expected
    downloaded = installer["downloads"].read_text()
    cached = success(run(installer, "--verify"))
    assert cached["cache_hit"] is True
    assert cached["cache_key"] == cold["cache_key"]
    assert installer["downloads"].read_text() == downloaded
    assert success(run(installer))["cache_hit"] is True
    assert installer["downloads"].read_text() == downloaded


def test_architecture_changes_cache_identity(installer, tmp_path):
    cold = success(run(installer))
    injected = tmp_path / "python-fixture"
    injected.mkdir()
    machine = "x86_64" if platform.machine() in {"arm64", "aarch64"} else "arm64"
    (injected / "sitecustomize.py").write_text(
        f"import platform\nplatform.machine = lambda: {machine!r}\n",
    )
    installer["env"]["PYTHONPATH"] = str(injected)
    changed = run(installer, "--cache-key")
    assert changed.returncode == 0
    assert changed.stdout.strip() != cold["cache_key"]
    result = run(installer, "--verify")
    assert result.returncode != 0
    assert "incompatible cache" in result.stderr


def test_missing_cache_verify_never_installs(installer):
    result = run(installer, "--verify")
    assert result.returncode != 0
    assert "missing, corrupt, or incompatible cache" in result.stderr
    assert not installer["downloads"].exists()
    assert not installer["prefix"].exists()


@pytest.mark.parametrize(
    "change",
    ["image", "manifest", "installer", "contents", "mode", "symlink"],
)
def test_corrupt_or_incompatible_cache_is_rejected_without_download(installer, change):
    cold = success(run(installer))
    downloaded = installer["downloads"].read_text()
    if change == "image":
        installer["env"]["ImageOS"] = "other-image"
    elif change == "manifest":
        installer["manifest"].write_text(installer["manifest"].read_text() + "\n")
    elif change == "installer":
        installer["script"].write_text(installer["script"].read_text() + "\n")
    elif change == "contents":
        (installer["prefix"] / "crane/crane").write_text("changed")
    elif change == "mode":
        (installer["prefix"] / "crane/crane").chmod(0o644)
    else:
        binary = installer["prefix"] / "bin/crane"
        binary.unlink()
        binary.symlink_to(installer["script"])
    rejected = run(installer, "--verify")
    assert rejected.returncode != 0
    assert "missing, corrupt, or incompatible cache" in rejected.stderr
    assert installer["downloads"].read_text() == downloaded
    if change in {"image", "manifest", "installer"}:
        key = run(installer, "--cache-key")
        assert key.returncode == 0
        assert key.stdout.strip() != cold["cache_key"]


def test_corrupt_cache_has_complete_reinstallation_path(installer):
    cold = success(run(installer))
    binary = installer["prefix"] / "crane/crane"
    original = binary.read_bytes()
    binary.write_text("corrupt")
    repaired = success(run(installer))
    assert repaired["cache_hit"] is False
    assert repaired["cache_key"] == cold["cache_key"]
    assert binary.read_bytes() == original
    assert success(run(installer, "--verify"))["cache_hit"] is True


@pytest.mark.parametrize("failure", ["checksum", "escape"])
def test_cold_install_rejects_bad_artifact(installer, failure):
    manifest = json.loads(installer["manifest"].read_text())
    artifact = manifest["tools"]["node"]["artifacts"]["all"]
    if failure == "checksum":
        artifact["sha256"] = "0" * 64
    else:
        path = Path(installer["env"]["FIXTURE_ARCHIVES"]) / "node.tgz"
        archive(path, "../escaped", "bad")
        artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    installer["manifest"].write_text(json.dumps(manifest))
    result = run(installer)
    assert result.returncode != 0
    assert (
        "checksum mismatch" in result.stderr
        if failure == "checksum"
        else "archive path escapes" in result.stderr
    )
    assert not installer["prefix"].exists()
    assert not (installer["prefix"].parent / "escaped").exists()


def test_valid_checksum_with_wrong_tool_version_is_rejected(installer):
    manifest = json.loads(installer["manifest"].read_text())
    path = Path(installer["env"]["FIXTURE_ARCHIVES"]) / "crane.tgz"
    archive(path, "crane", "#!/bin/sh\nprintf '%s\\n' '9.9.9'\n")
    manifest["tools"]["crane"]["artifacts"]["all"]["sha256"] = hashlib.sha256(
        path.read_bytes(),
    ).hexdigest()
    installer["manifest"].write_text(json.dumps(manifest))
    result = run(installer)
    assert result.returncode != 0
    assert "crane version mismatch" in result.stderr
    assert not installer["prefix"].exists()


@pytest.mark.parametrize("link_type", ["safe", "symlink", "hardlink"])
@pytest.mark.parametrize("archive_root", ["release", "./release"])
def test_stripped_archive_links_are_checked_before_extraction(
    installer,
    link_type,
    archive_root,
):
    manifest = json.loads(installer["manifest"].read_text())
    path = Path(installer["env"]["FIXTURE_ARCHIVES"]) / "node.tgz"
    with tarfile.open(path) as original:
        payload = original.extractfile("bin/node").read()
    with tarfile.open(path, "w:gz") as bundle:
        item = tarfile.TarInfo(f"{archive_root}/bin/node")
        item.size = len(payload)
        item.mode = 0o755
        bundle.addfile(item, io.BytesIO(payload))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            link = tarfile.TarInfo(
                f"{archive_root}/bin/symbolic"
                if kind == tarfile.SYMTYPE
                else f"{archive_root}/bin/hard",
            )
            link.type = kind
            link.linkname = (
                "node" if kind == tarfile.SYMTYPE else f"{archive_root}/bin/node"
            )
            if link_type == "symlink" and kind == tarfile.SYMTYPE:
                link.linkname = "../../outside"
            if link_type == "hardlink" and kind == tarfile.LNKTYPE:
                link.linkname = f"{archive_root}/../outside"
            bundle.addfile(link)
    artifact = manifest["tools"]["node"]["artifacts"]["all"]
    artifact["strip"] = archive_root.count("/") + 1
    artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    installer["manifest"].write_text(json.dumps(manifest))
    real_tar = shutil.which("tar")
    assert real_tar
    extracted = installer["prefix"].parent / "extracted.txt"
    tar = Path(installer["env"]["PATH"].split(os.pathsep)[0]) / "tar"
    tar.write_text(
        f"#!{sys.executable}\nimport os, sys\nfrom pathlib import Path\n"
        f"Path({str(extracted)!r}).touch()\n"
        f"os.execv({real_tar!r}, [{real_tar!r}, *sys.argv[1:]])\n",
    )
    tar.chmod(0o755)
    result = run(installer)
    if link_type == "safe":
        success(result)
        assert extracted.exists()
        installed = installer["prefix"] / "node/bin"
        assert (installed / "symbolic").read_bytes() == payload
        assert (installed / "hard").samefile(installed / "node")
        assert success(run(installer, "--verify"))["cache_hit"] is True
    else:
        assert result.returncode != 0
        assert "archive link escapes" in result.stderr
        assert not extracted.exists()
        assert not installer["prefix"].exists()
