"""Read real distribution metadata while replacing only container execution."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import venv
from pathlib import Path

import pytest

# Subprocess arguments below are fixed programs and temporary fixture paths.
# ruff: noqa: S603

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "collect_dependencies",
    ROOT / "pack" / "collect_dependencies.py",
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
MAPPING = json.loads((ROOT / "pack" / "dependencies.json").read_text())
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def environment(tmp_path):
    def create(name, distributions):
        directory = tmp_path / name
        venv.EnvBuilder(with_pip=False).create(directory)
        python = directory / "bin" / "python"
        result = subprocess.run(
            [
                str(python),
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        site = Path(result.stdout.strip())
        for index, (package, version) in enumerate(distributions):
            metadata = site / f"fixture_{index}-1.0.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n",
            )
        # Importing the package would fail even though its metadata is readable.
        (site / "torch.py").write_text("raise RuntimeError('GPU import forbidden')\n")
        return directory

    return create


@pytest.fixture
def invocation():
    return {
        "workflow_run": "123",
        "source_revision": "b" * 40,
        "matrix_digest": collector.content_digest([{"platform": "linux/amd64"}]),
        "mapping_digest": collector.content_digest(MAPPING),
    }


@pytest.fixture
def build():
    return {
        "job": "linux-amd64-cuda13.0-vllm0.29.0",
        "attempt": 1,
        "backend": "cuda",
        "service": "vllm",
        "image": "gpustack/runner:cuda13.0-vllm0.29.0",
        "platform": "linux/amd64",
        "image_digest": DIGEST,
    }


def mock_image(monkeypatch, directory, *, virtual_env=None, known_venv=None):
    calls = []

    def execute(image_ref, platform, backend, service, mapping, timeout):
        calls.append((image_ref, platform, backend, service))
        env = {**os.environ, "PATH": str(directory / "bin")}
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("VIRTUAL_ENV", None)
        if virtual_env is not None:
            env["VIRTUAL_ENV"] = str(virtual_env)
        command = collector.probe_command(backend, service)
        if known_venv is not None:
            assert command[-2] == "/opt/venv"
            command[-2] = str(known_venv)
        result = collector.run_command(
            command,
            input_text=json.dumps(mapping),
            env=env,
            timeout=timeout,
        )
        return json.loads(result)

    monkeypatch.setattr(collector, "run_image", execute)
    return calls


def test_collect_real_metadata_alias_order_and_raw_versions(
    environment,
    monkeypatch,
    invocation,
    build,
):
    directory = environment(
        "service",
        [
            ("Torch", "2.8.0rc1+GPU.Custom"),
            ("Mooncake_Transfer_Engine", "0.3.9"),
            ("mooncake-transfer-engine-rocm", "0.3.8rc2+rocm"),
            ("mooncake-transfer-engine-npu", "0.3.7.post1"),
        ],
    )
    calls = mock_image(monkeypatch, directory, virtual_env=directory)
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "succeeded"
    assert receipt["interpreter"] == str(directory / "bin" / "python")
    assert receipt["prefix"] == str(directory)
    assert receipt["distributions"] == {
        "torch": "2.8.0rc1+GPU.Custom",
        "mooncake-transfer-engine": "0.3.9",
        "mooncake-transfer-engine-rocm": "0.3.8rc2+rocm",
        "mooncake-transfer-engine-npu": "0.3.7.post1",
    }
    assert collector.fold_dependencies(receipt["distributions"], MAPPING) == {
        "torch": "2.8.0rc1+GPU.Custom",
        "mooncake-transfer-engine": "0.3.7.post1",
    }
    assert calls == [(f"gpustack/runner@{DIGEST}", "linux/amd64", "cuda", "vllm")]
    assert collector.validate_receipts(invocation, [build], MAPPING, [receipt]) == [
        receipt,
    ]


def test_rocm_sglang_venv_without_virtual_env(
    environment,
    monkeypatch,
    invocation,
    build,
):
    directory = environment("rocm", [("torch", "2.8.0+rocm6.4")])
    build.update(backend="rocm", service="sglang")
    mock_image(monkeypatch, directory, known_venv=directory)
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "succeeded"
    assert receipt["prefix"] == str(directory)
    assert receipt["distributions"] == {"torch": "2.8.0+rocm6.4"}


def test_missing_known_service_environment_fails_closed(
    environment,
    monkeypatch,
    invocation,
    build,
    tmp_path,
):
    directory = environment("path-python", [("torch", "1.0+system")])
    missing = tmp_path / "missing-service"
    assert not missing.exists()
    build.update(backend="rocm", service="sglang")
    mock_image(monkeypatch, directory, known_venv=missing)
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "failed"
    assert f"service interpreter unavailable: {missing}/bin/python" in receipt["error"]
    assert "distributions" not in receipt
    with pytest.raises(ValueError, match="failed"):
        collector.validate_receipts(invocation, [build], MAPPING, [receipt])


def test_empty_success_is_distinct_from_disabled(
    environment,
    monkeypatch,
    invocation,
    build,
):
    directory = environment("unrelated", [("unrelated-package", "1.0")])
    calls = mock_image(monkeypatch, directory)
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "succeeded"
    assert receipt["distributions"] == {}
    assert collector.fold_dependencies(receipt["distributions"], MAPPING) == {}
    unknown = collector.collect(invocation, build, MAPPING, disabled=True)
    assert unknown["status"] == "unknown"
    assert "distributions" not in unknown
    assert len(calls) == 1
    with pytest.raises(ValueError, match="unknown"):
        collector.validate_receipts(invocation, [build], MAPPING, [unknown])
    assert collector.validate_receipts(
        invocation,
        [build],
        MAPPING,
        [unknown],
        allow_unknown=True,
    ) == [unknown]


@pytest.mark.parametrize(
    "distributions",
    [
        [],
        [("torch", "")],
        [("", "1.0")],
        [("torch", "1.0"), ("Torch", "2.0")],
    ],
)
def test_invalid_metadata_fails(
    environment,
    monkeypatch,
    invocation,
    build,
    distributions,
):
    mock_image(monkeypatch, environment("broken", distributions))
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "failed"
    assert receipt["error"]
    assert "distributions" not in receipt
    with pytest.raises(ValueError, match="failed"):
        collector.validate_receipts(invocation, [build], MAPPING, [receipt])


@pytest.mark.parametrize(
    "selection",
    ["conflict", "unavailable", "missing-path", "rocm-conflict"],
)
def test_interpreter_selection_fails_closed(
    environment,
    monkeypatch,
    invocation,
    build,
    selection,
):
    directory = environment("service", [("torch", "2.0")])
    alternate = environment("alternate", [("torch", "1.0")])
    if selection == "rocm-conflict":
        build.update(backend="rocm", service="sglang")
        mock_image(monkeypatch, directory, known_venv=alternate)
    elif selection == "missing-path":
        mock_image(monkeypatch, directory / "missing")
    else:
        virtual_env = alternate if selection == "conflict" else directory / "missing"
        mock_image(monkeypatch, directory, virtual_env=virtual_env)
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "failed"
    assert "distributions" not in receipt


@pytest.fixture
def success(environment, monkeypatch, invocation, build):
    mock_image(monkeypatch, environment("success", [("torch", "2.8.0")]))
    return collector.collect(invocation, build, MAPPING)


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_digest", "sha256:" + "c" * 64),
        ("platform", "linux/arm64"),
        ("platform", "linux/amd64/v1"),
        ("image", "gpustack/runner:another"),
        ("backend", "rocm"),
        ("service", "sglang"),
        ("attempt", 2),
        ("job", "other-job"),
    ],
)
def test_reject_stale_build_identity(invocation, build, success, field, value):
    success["build"][field] = value
    with pytest.raises(ValueError, match="receipt build identity"):
        collector.validate_receipts(invocation, [build], MAPPING, [success])


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_run", "124"),
        ("source_revision", "d" * 40),
        ("matrix_digest", "sha256:" + "e" * 64),
        ("mapping_digest", "sha256:" + "f" * 64),
    ],
)
def test_reject_stale_invocation(invocation, build, success, field, value):
    success["invocation"][field] = value
    with pytest.raises(ValueError, match="receipt invocation"):
        collector.validate_receipts(invocation, [build], MAPPING, [success])


def test_mapping_alias_order_is_part_of_identity(invocation, build, success):
    changed = copy.deepcopy(MAPPING)
    changed["mooncake-transfer-engine"].reverse()
    assert collector.content_digest(changed) != invocation["mapping_digest"]
    with pytest.raises(ValueError, match="mapping"):
        collector.validate_receipts(invocation, [build], changed, [success])


@pytest.mark.parametrize(
    "kind",
    ["missing", "duplicate", "conflicting", "unexpected", "empty-matrix"],
)
def test_complete_set_required(invocation, build, success, kind):
    receipts = [success]
    builds = [build]
    if kind == "missing":
        receipts = []
    elif kind == "empty-matrix":
        builds = []
        receipts = []
    else:
        other = copy.deepcopy(success)
        if kind == "conflicting":
            other["distributions"]["torch"] = "0.0"
        elif kind == "unexpected":
            other["build"]["job"] = "unexpected"
        receipts.append(other)
    with pytest.raises(ValueError, match=r"missing|duplicate|unexpected|nonempty"):
        collector.validate_receipts(invocation, builds, MAPPING, receipts)


@pytest.mark.parametrize(
    "patch",
    [
        {"status": "failed", "error": "execution failed"},
        {"status": "unknown"},
        {"status": "success"},
        {"distributions": None},
        {"distributions": {"torch": 2}},
        {"distributions": {"torch": ""}},
        {"distributions": {"Torch": "2"}},
        {"distributions": {"unconfigured": "2"}},
        {"schema_version": 2},
        {"interpreter": ""},
        {"prefix": None},
    ],
)
def test_malformed_or_unsuccessful_receipt_rejected(invocation, build, success, patch):
    success.update(patch)
    with pytest.raises(ValueError, match=r"collection|distribution|receipt|schema"):
        collector.validate_receipts(invocation, [build], MAPPING, [success])


def test_platforms_and_partial_rerun_keep_independent_versions(
    environment,
    monkeypatch,
    invocation,
    build,
):
    arm = {
        **build,
        "job": "arm-job",
        "attempt": 2,
        "platform": "linux/arm64/v8",
        "image_digest": "sha256:" + "c" * 64,
    }
    mock_image(monkeypatch, environment("amd", [("vllm-omni", "0.18.0")]))
    amd_receipt = collector.collect(invocation, build, MAPPING)
    mock_image(monkeypatch, environment("arm", [("vllm-omni", "0.18.1rc1+arm")]))
    arm_receipt = collector.collect(invocation, arm, MAPPING)
    receipts = collector.validate_receipts(
        invocation,
        [build, arm],
        MAPPING,
        [arm_receipt, amd_receipt],
    )
    assert [r["distributions"] for r in receipts] == [
        {"vllm-omni": "0.18.0"},
        {"vllm-omni": "0.18.1rc1+arm"},
    ]
    stale = copy.deepcopy(arm_receipt)
    stale["build"]["attempt"] = 1
    with pytest.raises(ValueError, match="receipt build identity"):
        collector.validate_receipts(
            invocation,
            [build, arm],
            MAPPING,
            [amd_receipt, stale],
        )


def test_deadline_is_a_failure(environment, monkeypatch, invocation, build):
    directory = environment("waiting", [("torch", "1.0")])
    python = directory / "bin" / "python"
    python.unlink()
    python.write_text("#!/bin/sh\nexec /bin/sleep 5\n")
    python.chmod(0o755)
    mock_image(monkeypatch, directory)
    started = time.monotonic()
    receipt = collector.collect(invocation, build, MAPPING, timeout=0.1)
    assert time.monotonic() - started < 2
    assert receipt["status"] == "failed"
    assert "timeout" in receipt["error"].lower()


def test_cli_unknown_and_validation_fail_without_output_changes(
    tmp_path,
    invocation,
    build,
):
    files = {
        "invocation": invocation,
        "build": build,
        "builds": [build],
        "mapping": MAPPING,
    }
    for name, value in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    receipt = tmp_path / "receipt.json"
    command = [sys.executable, str(ROOT / "pack" / "collect_dependencies.py")]
    common = [
        "--invocation",
        str(tmp_path / "invocation.json"),
        "--mapping",
        str(tmp_path / "mapping.json"),
    ]
    result = subprocess.run(
        [
            *command,
            "collect",
            *common,
            "--build",
            str(tmp_path / "build.json"),
            "--output",
            str(receipt),
            "--disabled",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(receipt.read_text())["status"] == "unknown"
    output = tmp_path / "validated.json"
    output.write_text("unchanged\n")
    result = subprocess.run(
        [
            *command,
            "validate",
            *common,
            "--builds",
            str(tmp_path / "builds.json"),
            "--receipts",
            str(receipt),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "unknown" in result.stderr
    assert output.read_text() == "unchanged\n"


def test_unknown_cannot_carry_failure(invocation, build):
    receipt = collector.collect(invocation, build, MAPPING, disabled=True)
    receipt["error"] = "probe failed"
    with pytest.raises(ValueError, match="unknown"):
        collector.validate_receipts(
            invocation,
            [build],
            MAPPING,
            [receipt],
            allow_unknown=True,
        )


@pytest.mark.parametrize(
    "mapping",
    [{}, {"torch": []}, {"torch": ["Torch"]}, {"torch": ["torch", "torch"]}],
)
def test_bad_mapping_rejected(invocation, build, mapping):
    invocation["mapping_digest"] = collector.content_digest(mapping)
    with pytest.raises(ValueError, match=r"mapping|aliases"):
        collector.collect(invocation, build, mapping, disabled=True)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_unbounded_timeout_rejected(invocation, build, timeout):
    with pytest.raises(ValueError, match="timeout"):
        collector.collect(invocation, build, MAPPING, timeout=timeout, disabled=True)


def test_process_deadline_kills_children(tmp_path):
    spawned = tmp_path / "spawned"
    leaked = tmp_path / "leaked"
    child = (
        f"import time,pathlib; time.sleep(0.6); pathlib.Path({str(leaked)!r}).touch()"
    )
    parent = (
        "import subprocess,sys,time,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(spawned)!r}).write_text(str(p.pid)); time.sleep(5)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        collector.run_command([sys.executable, "-c", parent], timeout=0.3)
    assert spawned.is_file(), "the test must start a child before testing its deadline"
    assert time.monotonic() - started < 2
    time.sleep(0.6)
    assert not leaked.exists()


@pytest.fixture
def escaped_pipe_process(tmp_path):
    spawned = tmp_path / "escaped-child.json"
    child = "import time; time.sleep(3)"
    parent = (
        "import subprocess,sys,time,pathlib,json,os; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); "
        f"pathlib.Path({str(spawned)!r}).write_text(json.dumps("
        "{'parent':os.getpid(),'child':p.pid,'session':os.getsid(p.pid)})); "
        "print('started',flush=True); print('waiting',file=sys.stderr,flush=True); "
        "time.sleep(5)"
    )
    try:
        yield parent, spawned
    finally:
        if spawned.exists():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(json.loads(spawned.read_text())["child"], signal.SIGKILL)


def test_timeout_does_not_drain_escaped_child_pipes(escaped_pipe_process):
    parent, spawned = escaped_pipe_process
    command = [sys.executable, "-c", parent]
    timeout = 0.3
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        collector.run_command(command, timeout=timeout)
    elapsed = time.monotonic() - started
    processes = json.loads(spawned.read_text())
    assert processes["session"] == processes["child"]
    assert processes["session"] != processes["parent"]
    with pytest.raises(ProcessLookupError):
        os.kill(processes["parent"], 0)
    assert failure.value.cmd == command
    assert failure.value.timeout == timeout
    assert b"started" in failure.value.output
    assert b"waiting" in failure.value.stderr
    assert elapsed < 2


@pytest.mark.parametrize("phase", ["run", "cleanup"])
def test_docker_cleanup_is_bounded_with_escaped_pipes(
    monkeypatch,
    invocation,
    build,
    escaped_pipe_process,
    tmp_path,
    phase,
):
    parent, spawned = escaped_pipe_process
    cleanup = tmp_path / "cleanup.json"
    driver = tmp_path / "docker.py"
    driver.write_text(
        "import json,pathlib,sys,time\n"
        "if sys.argv[1] == 'pull':\n"
        "    print('pulled')\n"
        "elif sys.argv[1:3] == ['image', 'inspect']:\n"
        "    print(json.dumps([{'Os':'linux','Architecture':'amd64'}]))\n"
        "elif sys.argv[1] == 'run':\n"
        f"    if {phase == 'run'!r}: exec({parent!r})\n"
        "    print('probe failed',file=sys.stderr); sys.exit(7)\n"
        "elif sys.argv[1:3] == ['rm', '--force']:\n"
        f"    pathlib.Path({str(cleanup)!r}).write_text(json.dumps("
        "{'started':time.monotonic(),'args':sys.argv[1:]}))\n"
        f"    if {phase == 'cleanup'!r}: exec({parent!r})\n",
    )
    monkeypatch.setattr(collector.host_platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.host_platform, "machine", lambda: "x86_64")
    run_command = collector.run_command
    calls = []

    def execute(command, **kwargs):
        assert command[0] == "docker"
        calls.append((command, kwargs["timeout"]))
        if command[1] == "rm" and phase == "cleanup":
            # Exercise the real timeout path without a 15-second fixture wait.
            kwargs["timeout"] = 0.3
        return run_command([sys.executable, str(driver), *command[1:]], **kwargs)

    monkeypatch.setattr(collector, "run_command", execute)
    started = time.monotonic()
    receipt = collector.collect(invocation, build, MAPPING, timeout=0.5)
    elapsed = time.monotonic() - started
    assert spawned.exists(), "the Docker fixture must start its escaped child"
    removal = json.loads(cleanup.read_text())
    run = calls[2][0]
    assert removal["args"] == ["rm", "--force", run[run.index("--name") + 1]]
    assert calls[3][1] == 15
    assert receipt["status"] == "failed"
    if phase == "run":
        assert receipt["error"] == "collection timeout exceeded"
    else:
        assert "command failed (exit 7): probe failed" in receipt["error"]
        assert (
            "container cleanup failed: collection timeout exceeded" in receipt["error"]
        )
    assert removal["started"] - started < 2
    assert elapsed < 2


def fake_docker(
    monkeypatch,
    *,
    image_platform="linux/amd64",
    failure=None,
    cleanup_failure=False,
):
    monkeypatch.setattr(collector.host_platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.host_platform, "machine", lambda: "x86_64")
    parts = image_platform.split("/")
    image = {"Os": parts[0], "Architecture": parts[1]}
    if len(parts) > 2:
        image["Variant"] = parts[2]
    calls = []

    def execute(command, *, timeout, input_text=None):
        assert 0 < timeout <= 300
        calls.append(command)
        if command[1] == "pull":
            return "pulled"
        if command[1:3] == ["image", "inspect"]:
            return json.dumps([image])
        if command[1] == "run":
            assert json.loads(input_text) == MAPPING
            if failure is not None:
                raise failure
            return json.dumps(
                {
                    "interpreter": "/service/bin/python",
                    "prefix": "/service",
                    "distributions": {"torch": "2.0+raw"},
                },
            )
        assert command[1:3] == ["rm", "--force"]
        if cleanup_failure:
            raise subprocess.CalledProcessError(1, command, stderr="cleanup failed")
        return "removed"

    monkeypatch.setattr(collector, "run_command", execute)
    return calls


def test_docker_uses_digest_and_overrides_entrypoint(monkeypatch, invocation, build):
    calls = fake_docker(monkeypatch)
    build["image"] = "registry.example:5000/gpustack/runner:tag"
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "succeeded"
    reference = f"registry.example:5000/gpustack/runner@{DIGEST}"
    assert calls[0] == ["docker", "pull", "--platform", "linux/amd64", reference]
    assert calls[1] == ["docker", "image", "inspect", reference]
    run = calls[2]
    assert run[run.index("--entrypoint") + 1] == "/bin/sh"
    assert run[run.index("--platform") + 1] == "linux/amd64"
    assert run[run.index("-i") + 1] == reference
    assert len(calls) == 3


@pytest.mark.parametrize(
    "expected,inspected",
    [
        ("linux/arm64", "linux/arm64/v8"),
        ("linux/arm64/v8", "linux/arm64"),
        ("linux/amd64", "linux/amd64/v1"),
        ("linux/amd64/v1", "linux/amd64"),
    ],
)
def test_default_platform_variants_are_equivalent(
    monkeypatch,
    invocation,
    build,
    expected,
    inspected,
):
    calls = fake_docker(monkeypatch, image_platform=inspected)
    machine = "aarch64" if expected.split("/")[1] == "arm64" else "x86_64"
    monkeypatch.setattr(collector.host_platform, "machine", lambda: machine)
    build["platform"] = expected
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "succeeded"
    assert receipt["build"] == build
    assert calls[0][calls[0].index("--platform") + 1] == expected
    assert calls[2][calls[2].index("--platform") + 1] == expected
    assert collector.validate_receipts(invocation, [build], MAPPING, [receipt]) == [
        receipt,
    ]
    receipt["build"]["platform"] = inspected
    with pytest.raises(ValueError, match="receipt build identity"):
        collector.validate_receipts(invocation, [build], MAPPING, [receipt])


@pytest.mark.parametrize("system,machine", [("Darwin", "x86_64"), ("Linux", "aarch64")])
def test_non_native_runner_refused_before_docker(
    monkeypatch,
    invocation,
    build,
    system,
    machine,
):
    calls = fake_docker(monkeypatch)
    monkeypatch.setattr(collector.host_platform, "system", lambda: system)
    monkeypatch.setattr(collector.host_platform, "machine", lambda: machine)
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "failed"
    assert "native Linux" in receipt["error"]
    assert calls == []


@pytest.mark.parametrize(
    "expected,image_platform",
    [
        ("linux/amd64", "linux/arm64"),
        ("linux/amd64", "linux/amd64/v3"),
        ("linux/amd64/v3", "linux/amd64"),
        ("linux/amd64", "windows/amd64"),
        ("linux/arm64", "linux/arm64/v9"),
        ("linux/arm64/v9", "linux/arm64/v8"),
        ("linux/arm64/v8", "linux/amd64/v1"),
    ],
)
def test_image_platform_mismatch_refused(
    monkeypatch,
    invocation,
    build,
    expected,
    image_platform,
):
    calls = fake_docker(monkeypatch, image_platform=image_platform)
    machine = "aarch64" if expected.split("/")[1] == "arm64" else "x86_64"
    monkeypatch.setattr(collector.host_platform, "machine", lambda: machine)
    build["platform"] = expected
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "failed"
    assert "platform mismatch" in receipt["error"]
    assert len(calls) == 2


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_docker_timeout_removes_named_container(
    monkeypatch,
    invocation,
    build,
    cleanup_failure,
):
    calls = fake_docker(
        monkeypatch,
        failure=subprocess.TimeoutExpired("docker", 0.1),
        cleanup_failure=cleanup_failure,
    )
    receipt = collector.collect(invocation, build, MAPPING)
    assert receipt["status"] == "failed"
    assert "timeout" in receipt["error"].lower()
    if cleanup_failure:
        assert "cleanup failed" in receipt["error"]
    run = calls[2]
    assert calls[3] == ["docker", "rm", "--force", run[run.index("--name") + 1]]
