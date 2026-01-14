from __future__ import annotations

import json
import os
import platform as os_platform
import shutil
import subprocess
import sys
import tempfile
import time
from argparse import OPTIONAL
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from dataclasses_json import dataclass_json

from gpustack_runner import (
    BackendRunners,
    envs,
    list_backend_runners,
    merge_image,
    replace_image_with,
    split_image,
)

from .__types__ import SubCommand

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction

_AVAILABLE_BACKENDS = [
    "cann",
    "corex",
    "cuda",
    "dtk",
    "hggc",
    "maca",
    "musa",
    "neuware",
    "rocm",
]
_AVAILABLE_SERVICES = [
    "voxbox",
    "vllm",
    "mindie",
    "sglang",
]
_AVAILABLE_PLATFORMS = [
    "linux/amd64",
    "linux/arm64",
]


class ListImagesSubCommand(SubCommand):
    """
    Command to list images.
    """

    backend: str
    backend_version: str
    backend_version_prefix: str
    backend_variant: str
    service: str
    service_version: str
    service_version_prefix: str
    repository: str
    platform: str
    deprecated: bool
    format: str

    @staticmethod
    def register(parser: _SubParsersAction):
        list_parser = parser.add_parser(
            "list-images",
            help="List images",
        )

        list_parser.add_argument(
            "--backend",
            type=str,
            help="Filter gpustack/runner images by backend name",
            choices=_AVAILABLE_BACKENDS,
        )

        list_parser.add_argument(
            "--backend-version",
            type=str,
            help="Filter gpustack/runner images by exact backend version",
        )

        list_parser.add_argument(
            "--backend-version-prefix",
            type=str,
            help="Filter gpustack/runner images by backend version prefix",
        )

        list_parser.add_argument(
            "--backend-variant",
            type=str,
            help="Filter gpustack/runner images by backend variant",
        )

        list_parser.add_argument(
            "--service",
            type=str,
            help="Filter gpustack/runner images by service name",
            choices=_AVAILABLE_SERVICES,
        )

        list_parser.add_argument(
            "--service-version",
            type=str,
            help="Filter gpustack/runner images by exact service version",
        )

        list_parser.add_argument(
            "--service-version-prefix",
            type=str,
            help="Filter gpustack/runner images by service version prefix",
        )

        list_parser.add_argument(
            "--repository",
            type=str,
            help="Filter images by repository name",
        )

        list_parser.add_argument(
            "--platform",
            type=str,
            help="Filter images by platform",
            choices=_AVAILABLE_PLATFORMS,
        )

        list_parser.add_argument(
            "--deprecated",
            action="store_true",
            help="Include deprecated images in the listing",
        )

        list_parser.add_argument(
            "--format",
            type=str,
            help="Output format (default: text)",
            default="text",
            choices=["text", "json"],
        )

        list_parser.set_defaults(func=ListImagesSubCommand)

    def __init__(self, args: Namespace):
        self.backend = args.backend
        self.backend_version = args.backend_version
        self.backend_version_prefix = args.backend_version_prefix
        self.backend_variant = args.backend_variant
        self.service = args.service
        self.service_version = args.service_version
        self.service_version_prefix = args.service_version_prefix
        self.repository = args.repository
        self.platform = args.platform
        self.deprecated = args.deprecated or False
        self.format = args.format or "text"

    def run(self):
        images = list_images(
            backend=self.backend,
            backend_version=self.backend_version,
            backend_version_prefix=self.backend_version_prefix,
            backend_variant=self.backend_variant,
            service=self.service,
            service_version=self.service_version,
            service_version_prefix=self.service_version_prefix,
            repository=self.repository,
            platform=self.platform,
            with_deprecated=self.deprecated,
        )
        if not images:
            print("No matching images found.")
            return

        if self.format == "json":
            print(json.dumps([img.to_dict() for img in images], indent=2))
            return

        for img in images:
            print(img.name)


class SaveImagesSubCommand(SubCommand):
    """
    Command to save images to local that matched Docker/OCI archive.
    """

    backend: str
    backend_version: str
    backend_version_prefix: str
    backend_variant: str
    service: str
    service_version: str
    service_version_prefix: str
    repository: str
    platform: str
    deprecated: bool
    max_workers: int
    max_retries: int
    source: str
    source_namespace: str
    source_username: str
    source_password: str
    archive_format: str
    output: Path

    @staticmethod
    def register(parser: _SubParsersAction):
        save_parser = parser.add_parser(
            "save-images",
            help="Save images as OCI/Docker Archive to local path, "
            "powered by https://github.com/containers/skopeo",
        )

        save_parser.add_argument(
            "--backend",
            type=str,
            help="Filter gpustack/runner images by backend name",
            choices=_AVAILABLE_BACKENDS,
        )

        save_parser.add_argument(
            "--backend-version",
            type=str,
            help="Filter gpustack/runner images by exact backend version",
        )

        save_parser.add_argument(
            "--backend-version-prefix",
            type=str,
            help="Filter gpustack/runner images by backend version prefix",
        )

        save_parser.add_argument(
            "--backend-variant",
            type=str,
            help="Filter gpustack/runner images by backend variant",
        )

        save_parser.add_argument(
            "--service",
            type=str,
            help="Filter gpustack/runner images by service name",
            choices=_AVAILABLE_SERVICES,
        )

        save_parser.add_argument(
            "--service-version",
            type=str,
            help="Filter gpustack/runner images by exact service version",
        )

        save_parser.add_argument(
            "--service-version-prefix",
            type=str,
            help="Filter gpustack/runner images by service version prefix",
        )

        save_parser.add_argument(
            "--repository",
            type=str,
            help="Filter images by repository name",
        )

        save_parser.add_argument(
            "--platform",
            type=str,
            help="Filter images by platform (default: current platform)",
            choices=_AVAILABLE_PLATFORMS,
        )

        save_parser.add_argument(
            "--deprecated",
            action="store_true",
            help="Include deprecated images in the listing",
        )

        save_parser.add_argument(
            "--max-workers",
            type=int,
            default=1,
            help="Maximum number of worker threads to use for saving images concurrently (default: 1)",
        )

        save_parser.add_argument(
            "--max-retries",
            type=int,
            default=1,
            help="Maximum number of retries for saving an image (default: 1)",
        )

        save_parser.add_argument(
            "--source",
            "--src",
            type=str,
            default="docker.io",
            help="Source registry (default: docker.io)",
        )

        save_parser.add_argument(
            "--source-namespace",
            "--src-namespace",
            type=str,
            help="Namespace in the source registry",
        )

        save_parser.add_argument(
            "--source-username",
            "--src-user",
            type=str,
            help="Username for source registry authentication (env: SOURCE_USERNAME)",
        )

        save_parser.add_argument(
            "--source-password",
            "--src-passwd",
            type=str,
            help="Password/Token for source registry authentication "
            "(env: SOURCE_PASSWORD)",
        )

        save_parser.add_argument(
            "--archive-format",
            type=str,
            choices=["oci", "docker"],
            default="oci",
            help="Archive format to save (default: oci)",
        )

        save_parser.add_argument(
            "output",
            nargs=OPTIONAL,
            help="Output directory to save images (default: current working directory)",
        )

        save_parser.set_defaults(func=SaveImagesSubCommand)

    def __init__(self, args: Namespace):
        _ensure_required_tools()

        self.backend = args.backend
        self.backend_version = args.backend_version
        self.backend_version_prefix = args.backend_version_prefix
        self.backend_variant = args.backend_variant
        self.service = args.service
        self.service_version = args.service_version
        self.service_version_prefix = args.service_version_prefix
        self.repository = args.repository
        self.platform = args.platform or _get_current_platform()
        self.deprecated = args.deprecated or False
        self.max_workers = args.max_workers
        self.max_retries = args.max_retries
        self.source = args.source
        self.source_namespace = args.source_namespace
        self.source_username = args.source_username or os.getenv("SOURCE_USERNAME")
        self.source_password = args.source_password or os.getenv("SOURCE_PASSWORD")
        self.archive_format = args.archive_format
        self.output = Path(args.output or Path.cwd())

        try:
            if not self.output.exists():
                self.output.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            msg = (
                f"Failed to prepare output directory '{self.output}' for saving images"
            )
            raise RuntimeError(msg) from e

        if not self.output.is_dir():
            msg = f"Output path '{self.output}' is not a directory"
            raise RuntimeError(msg)

    def run(self):
        images = list_images(
            backend=self.backend,
            backend_version=self.backend_version,
            backend_version_prefix=self.backend_version_prefix,
            backend_variant=self.backend_variant,
            service=self.service,
            service_version=self.service_version,
            service_version_prefix=self.service_version_prefix,
            repository=self.repository,
            platform=self.platform,
            with_deprecated=self.deprecated,
        )
        if not images:
            print("No matching images found.")
            return

        if self.source_namespace:
            # The original name of image doesn't include registry,
            # but has namespace and repository, like: "namespace/repository:tag".
            for img in images:
                _, suffix = img.name.split("/", maxsplit=1)
                img.name = f"{self.source_namespace}/{suffix}"

        print("\033[2J\033[H", end="")

        saving_tasks: list[tuple[str, str, Path, Path]] = []
        print(
            f"Output: {self.output} | Archive: {self.archive_format} | Platform: {self.platform}",
        )
        print(f"Saving Images ({len(images)}):")
        for task_idx, img in enumerate(images):
            task_name = f"task-{task_idx:0>2d}"
            src_img = f"{self.source}/{img.name}"
            img_name, img_tag = split_image(src_img, fill_blank_tag=True)
            dst_file = self.output / img_name / f"{img_tag}.tar"
            dst_file_relative = dst_file.relative_to(self.output)
            saving_tasks.append(
                (task_name, src_img, dst_file, dst_file_relative),
            )
            print(
                f"  - [{task_name}]: {src_img} -> {dst_file_relative}",
            )
        print()

        for i in range(5, 0, -1):
            if sys.stdout.isatty():
                print(f"\rStarting in {i} seconds...", end="", flush=True)
            else:
                print(f"Starting in {i} seconds...")
            time.sleep(1)
        if sys.stdout.isatty():
            print("\rStarting now...              ", end="", flush=True)
        print()

        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="gpustack-saving-image",
        ) as executor:
            futures: dict[Future, tuple[str, str, Path, Path]] = {}
            failures: list[tuple[str, str, Path, str]] = []

            def check_result(f):
                _task_name, _src_img, _dst_file, _dst_file_relative = futures[f]
                try:
                    result = f.result()
                    if result.returncode == 0:
                        print(f"✅ Saved {_src_img} -> {_dst_file_relative}")
                        return
                    _save_err = result.stderr
                except subprocess.CalledProcessError as cpe:
                    _save_err = cpe.stderr if cpe.stderr else str(cpe)
                except CancelledError:
                    return
                except Exception as e:
                    _save_err = str(e)
                print(f"❌ Error saving {_src_img} -> {_dst_file_relative}")
                _dst_file.unlink(missing_ok=True)
                failures.append((_task_name, _src_img, _dst_file_relative, _save_err))

            override_os, override_arch = self.platform.split("/", maxsplit=1)

            # Submit tasks
            for task_name, src_img, dst_file, dst_file_relative in saving_tasks:
                if dst_file.exists():
                    print(f"✅ {dst_file} already exists, skipping save {src_img}.")
                    continue
                dst_file.parent.mkdir(parents=True, exist_ok=True, mode=0o744)

                command = [
                    "skopeo",
                    "copy",
                    "--src-tls-verify=false",
                    "--retry-times",
                    str(self.max_retries),
                    "--override-os",
                    override_os,
                    "--override-arch",
                    override_arch,
                ]
                if self.source_username and self.source_password:
                    command.extend(
                        [
                            "--src-creds",
                            f"{self.source_username}:{self.source_password}",
                        ],
                    )
                command.extend(
                    [
                        f"docker://{src_img}",
                        f"{self.archive_format}-archive:{dst_file}:{src_img}",
                    ],
                )

                future = executor.submit(
                    _execute_command,
                    title=task_name,
                    description=f"⏳ Saving {src_img} -> {dst_file_relative}...",
                    command=command,
                )
                future.add_done_callback(check_result)
                futures[future] = (task_name, src_img, dst_file, dst_file_relative)

            # Wait
            try:
                for _ in as_completed(futures):
                    pass
            except Exception:
                for future in futures:
                    future.cancel()
                raise

            # Review
            print()
            if failures:
                print(f"⚠️ Error saving {len(failures)} images:")
                for task_name, src_img, dst_file_relative, save_err in failures:
                    print(f"  - [{task_name}]: {src_img} -> {dst_file_relative}")
                    if save_err:
                        for line in save_err.splitlines():
                            print(f"      {line}")
                    else:
                        print("      (no error message)")
                sys.exit(1)


class CopyImagesSubCommand(SubCommand):
    """
    Command to copy images.
    """

    backend: str
    backend_version: str
    backend_version_prefix: str
    backend_variant: str
    service: str
    service_version: str
    service_version_prefix: str
    repository: str
    platform: str
    deprecated: bool
    max_workers: int
    max_retries: int
    source: str
    source_namespace: str
    source_username: str
    source_password: str
    destination: str
    destination_namespace: str
    destination_username: str
    destination_password: str

    @staticmethod
    def register(parser: _SubParsersAction):
        copy_parser = parser.add_parser(
            "copy-images",
            help="Copy images to other registry, "
            "powered by https://github.com/containers/skopeo",
        )

        copy_parser.add_argument(
            "--backend",
            type=str,
            help="Filter gpustack/runner images by backend name",
            choices=_AVAILABLE_BACKENDS,
        )

        copy_parser.add_argument(
            "--backend-version",
            type=str,
            help="Filter gpustack/runner images by exact backend version",
        )

        copy_parser.add_argument(
            "--backend-version-prefix",
            type=str,
            help="Filter gpustack/runner images by backend version prefix",
        )

        copy_parser.add_argument(
            "--backend-variant",
            type=str,
            help="Filter gpustack/runner images by backend variant",
        )

        copy_parser.add_argument(
            "--service",
            type=str,
            help="Filter gpustack/runner images by service name",
            choices=_AVAILABLE_SERVICES,
        )

        copy_parser.add_argument(
            "--service-version",
            type=str,
            help="Filter gpustack/runner images by exact service version",
        )

        copy_parser.add_argument(
            "--service-version-prefix",
            type=str,
            help="Filter gpustack/runner images by service version prefix",
        )

        copy_parser.add_argument(
            "--repository",
            type=str,
            help="Filter images by repository name",
        )

        copy_parser.add_argument(
            "--platform",
            type=str,
            help="Filter images by platform",
            choices=_AVAILABLE_PLATFORMS,
        )

        copy_parser.add_argument(
            "--deprecated",
            action="store_true",
            help="Include deprecated images in the listing",
        )

        copy_parser.add_argument(
            "--max-workers",
            type=int,
            default=1,
            help="Maximum number of worker threads to use for copying images concurrently (default: 1)",
        )

        copy_parser.add_argument(
            "--max-retries",
            type=int,
            default=1,
            help="Maximum number of retries for copying an image (default: 1)",
        )

        copy_parser.add_argument(
            "--source",
            "--src",
            type=str,
            default="docker.io",
            help="Source registry (default: docker.io)",
        )

        copy_parser.add_argument(
            "--source-namespace",
            "--src-namespace",
            type=str,
            help="Namespace in the source registry",
        )

        copy_parser.add_argument(
            "--source-username",
            "--src-user",
            type=str,
            help="Username for source registry authentication (env: SOURCE_USERNAME)",
        )

        copy_parser.add_argument(
            "--source-password",
            "--src-passwd",
            type=str,
            help="Password/Token for source registry authentication "
            "(env: SOURCE_PASSWORD)",
        )

        copy_parser.add_argument(
            "--destination",
            "--dest",
            type=str,
            help="Destination registry (default: docker.io) "
            "(env: GPUSTACK_RUNNER_DEFAULT_CONTAINER_REGISTRY, GPUSTACK_RUNTIME_DEPLOY_DEFAULT_CONTAINER_REGISTRY, GPUSTACK_SYSTEM_DEFAULT_CONTAINER_REGISTRY)",
        )

        copy_parser.add_argument(
            "--destination-namespace",
            "--dest-namespace",
            type=str,
            help="Namespace in the destination registry "
            "(env: GPUSTACK_RUNNER_DEFAULT_CONTAINER_NAMESPACE, GPUSTACK_RUNTIME_DEPLOY_DEFAULT_CONTAINER_NAMESPACE)",
        )

        copy_parser.add_argument(
            "--destination-username",
            "--dest-user",
            type=str,
            help="Username for destination registry authentication "
            "(env: DESTINATION_USERNAME)",
        )

        copy_parser.add_argument(
            "--destination-password",
            "--dest-passwd",
            type=str,
            help="Password/Token for destination registry authentication "
            "(env: DESTINATION_PASSWORD)",
        )

        copy_parser.set_defaults(func=CopyImagesSubCommand)

    def __init__(self, args: Namespace):
        _ensure_required_tools()

        self.backend = args.backend
        self.backend_version = args.backend_version
        self.backend_version_prefix = args.backend_version_prefix
        self.backend_variant = args.backend_variant
        self.service = args.service
        self.service_version = args.service_version
        self.service_version_prefix = args.service_version_prefix
        self.repository = args.repository
        self.platform = args.platform
        self.deprecated = args.deprecated or False
        self.max_workers = args.max_workers
        self.max_retries = args.max_retries
        self.source = args.source
        self.source_namespace = args.source_namespace
        self.source_username = args.source_username or os.getenv("SOURCE_USERNAME")
        self.source_password = args.source_password or os.getenv("SOURCE_PASSWORD")
        self.destination = (
            args.destination
            or envs.GPUSTACK_RUNNER_DEFAULT_CONTAINER_REGISTRY
            or "docker.io"
        )
        self.destination_namespace = (
            args.destination_namespace
            or envs.GPUSTACK_RUNNER_DEFAULT_CONTAINER_NAMESPACE
        )
        self.destination_username = args.destination_username or os.getenv(
            "DESTINATION_USERNAME",
        )
        self.destination_password = args.destination_password or os.getenv(
            "DESTINATION_PASSWORD",
        )

    def run(self):
        images = list_images(
            backend=self.backend,
            backend_version=self.backend_version,
            backend_version_prefix=self.backend_version_prefix,
            backend_variant=self.backend_variant,
            service=self.service,
            service_version=self.service_version,
            service_version_prefix=self.service_version_prefix,
            repository=self.repository,
            platform=self.platform,
            with_deprecated=self.deprecated,
        )
        if not images:
            print("No matching images found.")
            return

        if self.source_namespace:
            # The original name of image doesn't include registry,
            # but has namespace and repository, like: "namespace/repository:tag".
            for img in images:
                _, suffix = img.name.split("/", maxsplit=1)
                img.name = f"{self.source_namespace}/{suffix}"

        print("\033[2J\033[H", end="")

        copying_tasks: list[tuple[str, str, str]] = []
        print(f"Copying Images ({len(images)}):")
        for task_idx, img in enumerate(images):
            task_name = f"task-{task_idx:0>2d}"
            src_img = f"{self.source}/{img.name}"
            dst_img_name = img.name
            if self.destination_namespace:
                _, suffix = img.name.split("/", maxsplit=1)
                dst_img_name = f"{self.destination_namespace}/{suffix}"
            dst_img = f"{self.destination}/{dst_img_name}"
            copying_tasks.append(
                (task_name, src_img, dst_img),
            )
            print(f"  - [{task_name}]: {src_img} -> {dst_img}")
        print()

        for i in range(5, 0, -1):
            if sys.stdout.isatty():
                print(f"\rStarting in {i} seconds...   ", end="", flush=True)
            else:
                print(f"Starting in {i} seconds...")
            time.sleep(1)
        if sys.stdout.isatty():
            print("\rStarting now...              ", end="", flush=True)
        print()

        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="gpustack-copying-image",
        ) as executor:
            futures: dict[Future, tuple[str, str, str]] = {}
            failures: list[tuple[str, str, str, str]] = []

            def check_result(f):
                _task_name, _src_img, _dst_img = futures[f]
                try:
                    result = f.result()
                    if result.returncode == 0:
                        print(f"✅ Copied {_src_img} -> {_dst_img}")
                        return
                    _copy_err = result.stderr
                except subprocess.CalledProcessError as cpe:
                    _copy_err = cpe.stderr if cpe.stderr else str(cpe)
                except CancelledError:
                    return
                except Exception as e:
                    _copy_err = str(e)
                print(f"❌ Error copying {_src_img} -> {_dst_img}")
                failures.append((_task_name, _src_img, _dst_img, _copy_err))

            override_os, override_arch = None, None
            if self.platform:
                override_os, override_arch = self.platform.split("/", maxsplit=1)

            # Submit tasks
            for task_name, src_img, dst_img in copying_tasks:
                command = [
                    "skopeo",
                    "copy",
                    "--src-tls-verify=false",
                    "--dest-tls-verify=false",
                    "--retry-times",
                    str(self.max_retries),
                ]
                if override_os and override_arch:
                    command.extend(
                        [
                            "--override-os",
                            override_os,
                            "--override-arch",
                            override_arch,
                        ],
                    )
                else:
                    command.append("--all")
                if self.source_username and self.source_password:
                    command.extend(
                        [
                            "--src-creds",
                            f"{self.source_username}:{self.source_password}",
                        ],
                    )
                if self.destination_username and self.destination_password:
                    command.extend(
                        [
                            "--dest-creds",
                            f"{self.destination_username}:{self.destination_password}",
                        ],
                    )
                command.extend(
                    [
                        f"docker://{src_img}",
                        f"docker://{dst_img}",
                    ],
                )

                future = executor.submit(
                    _execute_command,
                    title=task_name,
                    description=f"⏳ Copying {src_img} -> {dst_img}...",
                    command=command,
                )
                future.add_done_callback(check_result)
                futures[future] = (task_name, src_img, dst_img)

            # Wait
            try:
                for _ in as_completed(futures):
                    pass
            except Exception:
                for future in futures:
                    future.cancel()
                raise

            # Review
            print()
            if failures:
                print(f"⚠️ Error copying {len(failures)} images:")
                for task_name, src_img, dst_img, copy_err in failures:
                    print(f"  - [{task_name}]: {src_img} -> {dst_img}:")
                    if copy_err:
                        for line in copy_err.splitlines():
                            print(f"      {line}")
                    else:
                        print("      (no error message)")
                sys.exit(1)


class LoadImagesSubCommand(SubCommand):
    """
    Command to load images to local container image storage that matched Docker/OCI archive.

    """

    repository: str
    platform: str
    max_workers: int
    max_retries: int
    destination: str
    destination_namespace: str
    archive_format: str
    storage: str
    input: Path
    archives: list[Path]

    @staticmethod
    def register(parser: _SubParsersAction):
        load_parser = parser.add_parser(
            "load-images",
            help="Load images from OCI/Docker Archive to local container image storage, "
            "powered by https://github.com/containers/skopeo",
        )

        load_parser.add_argument(
            "--repository",
            type=str,
            help="Filter images by repository name",
        )

        load_parser.add_argument(
            "--platform",
            type=str,
            help="Filter images by platform (default: current platform)",
            choices=_AVAILABLE_PLATFORMS,
        )

        load_parser.add_argument(
            "--max-workers",
            type=int,
            default=1,
            help="Maximum number of worker threads to use for loading images concurrently (default: 1)",
        )

        load_parser.add_argument(
            "--max-retries",
            type=int,
            default=1,
            help="Maximum number of retries for loading an image (default: 1)",
        )

        load_parser.add_argument(
            "--destination",
            "--dest",
            type=str,
            help="Override destination registry "
            "(env: GPUSTACK_RUNNER_DEFAULT_CONTAINER_REGISTRY, GPUSTACK_RUNTIME_DEPLOY_DEFAULT_CONTAINER_REGISTRY, GPUSTACK_SYSTEM_DEFAULT_CONTAINER_REGISTRY)",
        )

        load_parser.add_argument(
            "--destination-namespace",
            "--dest-namespace",
            type=str,
            help="Override namespace in the destination registry "
            "(env: GPUSTACK_RUNNER_DEFAULT_CONTAINER_NAMESPACE, GPUSTACK_RUNTIME_DEPLOY_DEFAULT_CONTAINER_NAMESPACE)",
        )

        load_parser.add_argument(
            "--archive-format",
            type=str,
            choices=["oci", "docker"],
            default="oci",
            help="Archive format to load (default: oci)",
        )

        load_parser.add_argument(
            "--storage",
            type=str,
            choices=["docker", "podman"],
            default="docker",
            help="Container image storage to load images into (default: docker)",
        )

        load_parser.add_argument(
            "input",
            nargs=OPTIONAL,
            help="Input directory to load images (default: current working directory)",
        )

        load_parser.set_defaults(func=LoadImagesSubCommand)

    def __init__(self, args: Namespace):
        _ensure_required_tools()

        self.repository = args.repository
        self.platform = args.platform or _get_current_platform()
        self.max_workers = args.max_workers
        self.max_retries = args.max_retries
        self.destination = (
            args.destination or envs.GPUSTACK_RUNNER_DEFAULT_CONTAINER_REGISTRY
        )
        self.destination_namespace = (
            args.destination_namespace
            or envs.GPUSTACK_RUNNER_DEFAULT_CONTAINER_NAMESPACE
        )
        self.archive_format = args.archive_format
        self.storage = args.storage
        self.input = Path(args.input)
        self.archives = []

        if not self.input.exists() or not self.input.is_dir():
            msg = f"Input path '{self.input}' is not a valid directory"
            raise RuntimeError(msg)

        if self.input.exists() and self.input.is_dir():
            for archive_path in self.input.rglob("*.tar"):
                if not archive_path.is_file():
                    continue
                if self.repository and archive_path.parent.name != self.repository:
                    continue
                self.archives.append(archive_path)

    def run(self):
        if not self.archives:
            print("No matching image archives found.")
            return

        print("\033[2J\033[H", end="")

        loading_tasks: list[tuple[str, Path, Path, str]] = []
        print(
            f"Input: {self.input} | Archive: {self.archive_format} | Storage: {self.storage}",
        )
        print(f"Loading Images ({len(self.archives)}):")
        for task_idx, src_file in enumerate(self.archives):
            task_name = f"task-{task_idx:0>2d}"
            src_file_relative = src_file.relative_to(self.input)
            dst_img_repo = str(src_file.parent.relative_to(self.input))
            dst_img_tag = src_file.name.removesuffix(src_file.suffix)
            dst_img = replace_image_with(
                merge_image(dst_img_repo, dst_img_tag),
                registry=self.destination,
                namespace=self.destination_namespace,
            )
            loading_tasks.append(
                (task_name, src_file, src_file_relative, dst_img),
            )
            print(f"  - [{task_name}]: {src_file_relative} -> {dst_img}")
        print()

        for i in range(5, 0, -1):
            if sys.stdout.isatty():
                print(f"\rStarting in {i} seconds...   ", end="", flush=True)
            else:
                print(f"Starting in {i} seconds...")
            time.sleep(1)
        if sys.stdout.isatty():
            print("\rStarting now...              ", end="", flush=True)
        print()

        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="gpustack-loading-image",
        ) as executor:
            futures: dict[Future, tuple[str, Path, str]] = {}
            failures: list[tuple[str, Path, str, str]] = []

            def check_result(f):
                _task_name, _src_file_relative, _dst_img = futures[f]
                try:
                    result = f.result()
                    if result.returncode == 0:
                        print(
                            f"✅ Loaded {_src_file_relative} -> {_dst_img}",
                        )
                        return
                    _load_err = result.stderr
                except subprocess.CalledProcessError as cpe:
                    _load_err = cpe.stderr if cpe.stderr else str(cpe)
                except CancelledError:
                    return
                except Exception as e:
                    _load_err = str(e)
                print(f"❌ Error loading {_src_file_relative} -> {_dst_img}")
                failures.append((_task_name, _src_file_relative, _dst_img, _load_err))

            override_os, override_arch = self.platform.split("/", maxsplit=1)

            # Submit tasks
            for task_name, src_file, src_file_relative, dst_img in loading_tasks:
                command = [
                    "skopeo",
                    "copy",
                    "--dest-tls-verify=false",
                    "--retry-times",
                    str(self.max_retries),
                    "--override-os",
                    override_os,
                    "--override-arch",
                    override_arch,
                    f"{self.archive_format}-archive:{src_file}",
                ]
                if self.storage == "docker":
                    command.append(
                        f"docker-daemon:{dst_img}",
                    )
                else:
                    command.append(
                        f"containers-storage:{dst_img}",
                    )

                future = executor.submit(
                    _execute_command,
                    title=task_name,
                    description=f"⏳ Loading {src_file_relative} -> {dst_img}...",
                    command=command,
                )
                future.add_done_callback(check_result)
                futures[future] = (task_name, src_file_relative, dst_img)

            # Wait
            try:
                for _ in as_completed(futures):
                    pass
            except Exception:
                for future in futures:
                    future.cancel()
                raise

            # Review
            print()
            if failures:
                print(f"⚠️ Error loading {len(failures)} images:")
                for task_name, src_file_relative, dst_img, load_err in failures:
                    print(f"  - [{task_name}]: {src_file_relative} -> {dst_img}:")
                    if load_err:
                        for line in load_err.splitlines():
                            print(f"      {line}")
                    else:
                        print("      (no error message)")
                sys.exit(1)


class CompareImagesSubCommand(SubCommand):
    """
    Command to compare images.
    """

    backend: str
    backend_variant: str
    service: str
    platform: str
    target: str
    color: bool
    refresh: bool

    @staticmethod
    def register(parser: _SubParsersAction):
        compare_parser = parser.add_parser(
            "compare-images",
            help="Compare images with another versioned GPUStack runner",
        )

        compare_parser.add_argument(
            "--backend",
            type=str,
            help="Filter gpustack/runner images by backend name",
            choices=_AVAILABLE_BACKENDS,
        )

        compare_parser.add_argument(
            "--backend-variant",
            type=str,
            help="Filter gpustack/runner images by backend variant",
        )

        compare_parser.add_argument(
            "--service",
            type=str,
            help="Filter gpustack/runner images by service name",
            choices=_AVAILABLE_SERVICES,
        )

        compare_parser.add_argument(
            "--platform",
            type=str,
            help="Filter images by platform",
            choices=_AVAILABLE_PLATFORMS,
        )

        compare_parser.add_argument(
            "--target",
            type=str,
            help="Target versioned gpustack/runner to compare images with",
            required=True,
        )

        compare_parser.add_argument(
            "--no-color",
            action="store_true",
            help="Disable colored output",
        )

        compare_parser.add_argument(
            "--refresh",
            action="store_true",
            help="Refresh the target versioned gpustack/runner metadata, "
            "default, it will use cached file if exists",
        )

        compare_parser.set_defaults(func=CompareImagesSubCommand)

    def __init__(self, args: Namespace):
        self.backend = args.backend
        self.backend_variant = args.backend_variant
        self.service = args.service
        self.platform = args.platform
        self.target = args.target
        self.color = not args.no_color
        self.refresh = args.refresh

        if not self.target:
            msg = "Target versioned gpustack/runner is required."
            raise RuntimeError(msg)

    def run(self):
        if not self.target.startswith("v"):
            self.target = f"v{self.target}"
        if ".post" in self.target and self.target != "v0.1.15.post1":
            self.target = self.target.replace(".post", "post")

        target_py_json_path = (
            Path(tempfile.gettempdir()) / f"runner_{self.target}.py.json"
        )
        if not target_py_json_path.exists() or self.refresh:
            target_py_json_uri = (
                f"https://raw.githubusercontent.com/gpustack/runner/refs/tags/"
                f"{self.target}/gpustack_runner/runner.py.json"
            )
            with requests.get(
                target_py_json_uri,
                stream=True,
                timeout=600,
                allow_redirects=True,
            ) as response:
                if response.ok:
                    with target_py_json_path.open("wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                else:
                    msg = (
                        f"Failed to fetch target versioned gpustack/runner from '{target_py_json_uri}', "
                        f"status code: {response.status_code}"
                    )
                    raise RuntimeError(
                        msg,
                    )

        current_images = list_images(
            backend=self.backend,
            backend_variant=self.backend_variant,
            service=self.service,
            platform=self.platform,
        )

        target_images = list_images(
            data_path=str(target_py_json_path),
            backend=self.backend,
            backend_variant=self.backend_variant,
            service=self.service,
            platform=self.platform,
        )

        current_images_mapping = {img.name: img.deprecated for img in current_images}
        target_images_mapping = {img.name: img.deprecated for img in target_images}

        # Added images
        added_image_names = [
            img_name
            for img_name in current_images_mapping
            if img_name not in target_images_mapping
        ]
        # Deprecated images
        deprecated_image_names = [
            img_name
            for img_name, depr in current_images_mapping.items()
            if (
                img_name not in added_image_names
                and depr
                and not target_images_mapping[img_name]
            )
        ]
        # Removed images
        removed_image_names = [
            img_name
            for img_name in target_images_mapping
            if img_name not in current_images_mapping
        ]

        green, cyan, red, reset = "\033[32m", "\033[36m", "\033[31m", "\033[0m"
        if not self.color:
            green, cyan, red, reset = "", "", "", ""
        for img_name in added_image_names:
            print(f"{green}+ {img_name}{reset}")
        for img_name in deprecated_image_names:
            print(f"{cyan}~ {img_name}{reset}")
        for img_name in removed_image_names:
            print(f"{red}- {img_name}{reset}")


@dataclass_json
@dataclass
class PlatformedImage:
    name: str
    """
    The name of the image.
    """
    platforms: list[str] | None = None
    """
    The platforms supported by the image.
    None means do not care the platform.
    """
    deprecated: bool = False
    """
    Whether the image is deprecated.
    """


_EXTRA_IMAGES: list[PlatformedImage] = []


def append_images(*images: PlatformedImage | str):
    """
    Appends extra images to the global list of extra images.

    Args:
        images: The images to append.

    """
    for img in images:
        if isinstance(img, str):
            _EXTRA_IMAGES.append(PlatformedImage(name=img))
        else:
            _EXTRA_IMAGES.append(img)


def list_images(**kwargs) -> list[PlatformedImage]:
    """
    Lists available images based on the provided filters.

    Args:
        **kwargs: Filtering criteria for listing images.

    Returns:
        A list of platformed images.

    """
    platform = kwargs.pop("platform", None)
    repository = kwargs.pop("repository", None)

    image_names_index: dict[str, int] = {}
    images: list[PlatformedImage] = []

    backend_runners: BackendRunners = list_backend_runners(**kwargs)
    for runner in backend_runners or []:
        for b_version in runner.versions:
            for b_variant in b_version.variants:
                for service in b_variant.services:
                    for s_version in service.versions:
                        depr = s_version.deprecated
                        for sr in s_version.platforms:
                            name, plat = sr.docker_image, sr.platform
                            if not name:
                                continue
                            if name not in image_names_index:
                                image_names_index[name] = len(images)
                                images.append(
                                    PlatformedImage(
                                        name=name,
                                        platforms=[plat],
                                        deprecated=depr,
                                    ),
                                )
                            else:
                                index = image_names_index[name]
                                if plat not in images[index].platforms:
                                    images[index].platforms.append(plat)

    if _EXTRA_IMAGES:
        for img in _EXTRA_IMAGES:
            name = img.name
            if not name:
                continue
            if name not in image_names_index:
                image_names_index[name] = len(images)
                images.append(img)
            else:
                index = image_names_index[name]
                if img.platforms:
                    images[index].platforms = images[index].platforms or []
                    for plat in img.platforms:
                        if plat not in images[index].platforms:
                            images[index].platforms.append(plat)

    if platform:
        images = [
            img for img in images if img.platforms is None or platform in img.platforms
        ]
    if repository:
        images = [img for img in images if img.name.__contains__(f"/{repository}:")]

    return images


def _ensure_required_tools():
    """
    Ensures if required tools are installed.

    Raises:
        RuntimeError: If tool is not found.

    """
    if not shutil.which("skopeo"):
        msg = "Skopeo is not found. Please follow https://github.com/containers/skopeo/blob/v1.13.3/install.md to install."
        raise RuntimeError(msg)


def _get_current_platform() -> str:
    """
    Get the current platform in the format "linux/{arch}".

    Returns:
        The current platform string.

    """
    arch = os_platform.machine().lower()
    match arch:
        case "x86_64" | "amd64":
            return "linux/amd64"
        case "aarch64" | "arm64":
            return "linux/arm64"

    return f"linux/{arch}"


def _execute_command(
    title: str,
    description: str,
    command: list[str],
) -> subprocess.CompletedProcess:
    """
    Executes a command and returns its output.

    Args:
        title:
            The title to prefix each line of output.
        description:
            A brief description of the command being executed.
        command:
            The command to execute as a list of strings.

    Returns:
        The completed process containing the command's output.

    """
    print(description)

    with subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        while True:
            line = process.stdout.readline()
            if line:
                # Print the line with the title prefix
                print(f"[{title}]: {line}", end="")
                sys.stdout.flush()
            elif process.poll() is not None:
                # Process has terminated, break after reading any remaining output
                break

        # Read any remaining output after process terminates
        remaining = process.stdout.read()
        if remaining:
            print(f"[{title}]: {remaining}", end="")
            sys.stdout.flush()

        # Wait for the process to complete and get the return code
        returncode = process.wait()
        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=returncode,
                cmd=command,
            )

        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
        )
