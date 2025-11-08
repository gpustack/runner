# PYTHON_ARGCOMPLETE_OK
from __future__ import annotations

import sys
from argparse import ArgumentParser

import argcomplete

from ._version import commit_id, version
from .cmds import (
    CopyImagesSubCommand,
    ListImagesSubCommand,
    SaveImagesSubCommand,
)


def main():
    parser = ArgumentParser(
        "gpustack-runner",
        description="GPUStack Runner CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}({commit_id})",
        help="show the version and exit",
    )

    # Register
    subcommand_parser = parser.add_subparsers(
        help="gpustack-runner command helpers",
    )
    ListImagesSubCommand.register(subcommand_parser)
    SaveImagesSubCommand.register(subcommand_parser)
    CopyImagesSubCommand.register(subcommand_parser)

    # Autocomplete
    argcomplete.autocomplete(parser)

    # Parse
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    # Run
    service = args.func(args)
    try:
        service.run()
    except KeyboardInterrupt:
        print("\033[2J\033[H", end="")


if __name__ == "__main__":
    main()
