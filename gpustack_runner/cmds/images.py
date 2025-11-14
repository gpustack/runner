from __future__ import annotations

import json
import os
import platform as os_platform
import shutil
import subprocess
import sys
import time
from argparse import OPTIONAL
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dataclasses_json import dataclass_json

from gpustack_runner import BackendRunners, list_backend_runners

from .__types__ import SubCommand

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction

_AVAILABLE_BACKENDS = [
    "cann",
    "corex",
    "cuda",
    "dtk",
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
    Command to save images to local that matched Docker Archive.
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
    max_workers: int
    max_retries: int
    source: str
    source_namespace: str
    source_username: str
    source_password: str
    output: Path

    @staticmethod
    def register(parser: _SubParsersAction):
        save_parser = parser.add_parser(
            "save-images",
            help="Save images as Docker Archive to local path, "
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
            help="Source namespace in the source registry, "
            "if the namespace has multiple levels, "
            "please specify the parent levels to --source, "
            "e.g --source my.registry.com/a/b --source-namespace c",
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
            help="Password/Token for source registry authentication (env: SOURCE_PASSWORD)",
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
        self.max_workers = args.max_workers
        self.max_retries = args.max_retries
        self.source = args.source
        self.source_namespace = args.source_namespace
        self.source_username = args.source_username or os.getenv("SOURCE_USERNAME")
        self.source_password = args.source_password or os.getenv("SOURCE_PASSWORD")
        self.output = Path(args.output or Path.cwd())

        try:
            if not self.output.exists():
                self.output.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            msg = f"Failed to create output directory '{self.output}'"
            raise RuntimeError(
                msg,
            ) from e

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

        print(f"Output Directory: {self.output}")
        print(f"Image Platform: {self.platform} ")
        print(f"Total Images ({len(images)}): ")
        for img in images:
            print("  -", img.name)
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
            futures = {}
            failures = []

            def check_result(f):
                img_name, img_output = futures[f]
                try:
                    result = f.result()
                    if result.returncode == 0:
                        print(f"✅ Downloaded image '{img_name}'")
                        return
                    img_err = result.stderr
                except subprocess.CalledProcessError as cpe:
                    img_err = cpe.stderr if cpe.stderr else str(cpe)
                except CancelledError:
                    return
                except Exception as e:
                    img_err = str(e)
                print(f"❌ Error downloading image '{img_name}'")
                failures.append((img_name, img_err))
                img_output.unlink(missing_ok=True)

            override_os, override_arch = self.platform.split("/", maxsplit=1)

            # Submit tasks
            for img in images:
                output_path = (
                    self.output / f"{img.name.replace('/', '-').replace(':', '_')}.tar"
                )
                if output_path.exists():
                    print(f"Image {img.name} already exists, skipping download.")
                    continue

                command = [
                    "skopeo",
                    "--override-os",
                    override_os,
                    "--override-arch",
                    override_arch,
                    "copy",
                    "--src-tls-verify",
                    "--retry-times",
                    str(self.max_retries),
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
                        f"docker://{self.source}/{img.name}",
                        f"docker-archive:{output_path}",
                    ],
                )

                future = executor.submit(
                    _execute_command,
                    title=img.name,
                    description=f"⏳ Downloading image '{img.name}'...",
                    command=command,
                )
                future.add_done_callback(check_result)
                futures[future] = (img.name, output_path)

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
                print(f"⚠️ Error downloading {len(failures)} images:")
                for name, err in failures:
                    print(f"  - {name}:")
                    if err:
                        for line in err.splitlines():
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
            help="Source namespace in the source registry, "
            "if the namespace has multiple levels, "
            "please specify the parent levels to --source, "
            "e.g --source my.registry.com/a/b --source-namespace c",
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
            help="Password/Token for source registry authentication (env: SOURCE_PASSWORD)",
        )

        copy_parser.add_argument(
            "--destination",
            "--dest",
            type=str,
            default="docker.io",
            help="Destination registry (default: docker.io)",
        )

        copy_parser.add_argument(
            "--destination-namespace",
            "--dest-namespace",
            type=str,
            help="Source namespace in the destination registry, "
            "if the namespace has multiple levels, "
            "please specify the parent levels to --destination, "
            "e.g --destination my.registry.com/a/b --destination-namespace c",
        )

        copy_parser.add_argument(
            "--destination-username",
            "--dest-user",
            type=str,
            help="Username for destination registry authentication (env: DESTINATION_USERNAME)",
        )

        copy_parser.add_argument(
            "--destination-password",
            "--dest-passwd",
            type=str,
            help="Password/Token for destination registry authentication (env: DESTINATION_PASSWORD)",
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
        self.max_workers = args.max_workers
        self.max_retries = args.max_retries
        self.source = args.source
        self.source_namespace = args.source_namespace
        self.source_username = args.source_username or os.getenv("SOURCE_USERNAME")
        self.source_password = args.source_password or os.getenv("SOURCE_PASSWORD")
        self.destination = args.destination
        self.destination_namespace = args.destination_namespace
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

        print(f"Destination: {self.destination}")
        print(f"Source: {self.source} ")
        print(f"Total Images ({len(images)}): ")
        for img in images:
            print("  -", img.name)
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
            futures = {}
            failures = []

            def check_result(f):
                img_name = futures[f]
                try:
                    result = f.result()
                    if result.returncode == 0:
                        print(f"✅ Synced image '{img_name}'")
                        return
                    img_err = result.stderr
                except subprocess.CalledProcessError as cpe:
                    img_err = cpe.stderr if cpe.stderr else str(cpe)
                except CancelledError:
                    return
                except Exception as e:
                    img_err = str(e)
                print(f"❌ Error syncing image '{img_name}'")
                failures.append((img_name, img_err))

            # Submit tasks
            for img in images:
                command = [
                    "skopeo",
                    "copy",
                    "--src-tls-verify",
                    "--dest-tls-verify",
                    "--all",
                    "--retry-times",
                    str(self.max_retries),
                ]
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
                dest_img_name = img.name
                if self.destination_namespace:
                    _, suffix = img.name.split("/", maxsplit=1)
                    dest_img_name = f"{self.destination_namespace}/{suffix}"
                command.extend(
                    [
                        f"docker://{self.source}/{img.name}",
                        f"docker://{self.destination}/{dest_img_name}",
                    ],
                )

                future = executor.submit(
                    _execute_command,
                    title=img.name,
                    description=(
                        f"⏳ Syncing image '{img.name}' to '{dest_img_name}'..."
                        if img.name != dest_img_name
                        else f"⏳ Syncing image '{img.name}'..."
                    ),
                    command=command,
                )
                future.add_done_callback(check_result)
                futures[future] = img.name

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
                print(f"⚠️ Error syncing {len(failures)} images:")
                for name, err in failures:
                    print(f"  - {name}:")
                    if err:
                        for line in err.splitlines():
                            print(f"      {line}")
                    else:
                        print("      (no error message)")
                sys.exit(1)


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
