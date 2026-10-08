"""
Read installed distribution metadata without importing service packages.

The collector sends this program to the service interpreter with ``-c``.
Standard input contains the dependency mapping; standard output is one JSON object.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import sys


def probe(mapping: dict[str, list[str]]) -> dict:
    wanted = {name for aliases in mapping.values() for name in aliases}
    if not wanted:
        message = "dependency mapping is empty"
        raise ValueError(message)
    installed = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.metadata.get("Version")
        if not name or not version:
            message = "installed distribution has missing Name or Version metadata"
            raise ValueError(message)
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in installed and installed[name] != version:
            message = f"conflicting installed distribution versions: {name}"
            raise ValueError(message)
        installed[name] = version
    # An empty environment is not evidence that a service lacks selected packages.
    if not installed:
        message = "enumerated 0 installed distributions in the service environment"
        raise ValueError(message)
    return {
        "interpreter": sys.executable,
        "prefix": sys.prefix,
        "distributions": {
            name: installed[name] for name in sorted(wanted) if name in installed
        },
    }


if __name__ == "__main__":
    try:
        print(json.dumps(probe(json.load(sys.stdin))))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
