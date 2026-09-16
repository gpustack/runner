#!/usr/bin/env bash

# Probe the versions of whitelisted Python packages installed in the image, and
# write them to a JSON file that ships inside the image and is exported from the
# build to feed `dependencies` in runner.py.json.
#
# This is the single copy shared by every backend, reached through the buildx
# named build context `shared`, never through a backend's own build context.
#
# Usage:
#   DEPENDENCY_PACKAGES="lmcache torch ray ..." probe_dependencies.sh [OUTPUT_PATH]
#
# Output is a flat map, keys PEP 503 normalized and sorted, holding only the
# packages actually installed, under their raw distribution names:
#   {"lmcache-ascend": "0.5.4", "lmcache": "0.4.3", "torch": "2.13.0"}
# `pack/merge_runner.sh` folds those names onto the dependency names of
# `pack/dependencies.json` before they reach runner.py.json; this file keeps the
# unfolded truth for troubleshooting.
#
# Three outcomes, deliberately distinguishable -- an empty map and a failed probe
# must never look alike:
#   - DEPENDENCY_PACKAGES empty  -> skip, exit 0, NO file written. A missing file
#     means "never probed", mirroring an absent `dependencies` field, and makes
#     the export stage fail loudly rather than export an empty map.
#   - probed, nothing matched    -> exit 0, OUTPUT_PATH contains `{}`.
#   - probe failed               -> exit 1, the build fails.
#
# The environment is enumerated once with `pip list` rather than one `pip show`
# per package: `pip show` exits non-zero both when a package is missing and when
# the tool itself is broken (e.g. `uv pip` outside a virtualenv), so it cannot
# tell "not installed" from "probe failed" and would silently report `{}`.

set -eo pipefail

OUTPUT_PATH="${1:-/etc/gpustack-runner/dependencies.json}"

if [[ -z "${DEPENDENCY_PACKAGES// /}" ]]; then
    echo "[INFO]: DEPENDENCY_PACKAGES is empty, skipping dependency probing"
    exit 0
fi

# Resolve a probing tool. Fail loudly rather than emitting an empty map.
if command -v uv >/dev/null 2>&1; then
    PROBE_TOOL="uv"
    # Most images set this themselves, but not necessarily in the stage this
    # script runs in: without it `uv pip` refuses to work outside a virtualenv.
    export UV_SYSTEM_PYTHON=1
    LIST_CMD=(uv pip list --format=json)
elif command -v pip >/dev/null 2>&1; then
    PROBE_TOOL="pip"
    LIST_CMD=(pip list --format=json)
elif command -v pip3 >/dev/null 2>&1; then
    PROBE_TOOL="pip3"
    LIST_CMD=(pip3 list --format=json)
else
    echo "[ERROR]: neither uv nor pip is available, cannot probe dependencies" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR]: python3 is not available, cannot probe dependencies" >&2
    exit 1
fi

echo "[INFO]: probing with '${PROBE_TOOL}'"

# Capture stderr rather than discarding it: the usual trigger is uv/pip pointed
# at the wrong environment in this stage, which only shows up there.
LIST_STDERR_FILE="$(mktemp)"
LIST_EXIT=0
INSTALLED_JSON="$("${LIST_CMD[@]}" 2>"${LIST_STDERR_FILE}")" || LIST_EXIT=$?
LIST_STDERR="$(cat "${LIST_STDERR_FILE}")"
rm -f "${LIST_STDERR_FILE}"

if [[ ${LIST_EXIT} -ne 0 || -z "${INSTALLED_JSON}" ]]; then
    echo "[ERROR]: '${LIST_CMD[*]}' failed (exit ${LIST_EXIT}), cannot probe dependencies" >&2
    if [[ -n "${LIST_STDERR}" ]]; then
        echo "[ERROR]: stderr was:" >&2
        echo "${LIST_STDERR}" | sed 's/^/[ERROR]:   /' >&2
    fi
    exit 1
fi

mkdir -p "$(dirname "${OUTPUT_PATH}")"

INSTALLED_JSON="${INSTALLED_JSON}" \
DEPENDENCY_PACKAGES="${DEPENDENCY_PACKAGES}" \
OUTPUT_PATH="${OUTPUT_PATH}" \
python3 - <<'PYTHON'
import json
import os
import re
import sys


def normalize(name):
    # PEP 503 normalization.
    return re.sub(r"[-_.]+", "-", name).lower()


try:
    enumerated = json.loads(os.environ["INSTALLED_JSON"])
except ValueError as e:
    print(f"[ERROR]: cannot parse the installed package list: {e}", file=sys.stderr)
    sys.exit(1)

installed = {normalize(item["name"]): item["version"] for item in enumerated}

# A real runner image always has packages installed. An empty enumeration means
# the probing tool pointed at the wrong Python environment, which must not be
# reported as "nothing from the whitelist is installed".
if not installed:
    print("[ERROR]: enumerated 0 installed packages, the probing tool is looking at the wrong environment", file=sys.stderr)
    sys.exit(1)

wanted = sorted({normalize(n) for n in os.environ["DEPENDENCY_PACKAGES"].split()})

# A whitespace-only value (e.g. a stray tab) slips past the bash-side empty
# check but yields zero names here, and would be written out as a plausible
# `{}`. Hard failure instead -- see the three outcomes in the header.
if not wanted:
    print("[ERROR]: DEPENDENCY_PACKAGES is whitespace-only, no package names to probe", file=sys.stderr)
    sys.exit(1)

packages = {}
for name in wanted:
    version = installed.get(name)
    if version is None:
        print(f"[INFO]:   {name}: not installed")
        continue
    print(f"[INFO]:   {name}: {version}")
    packages[name] = version

with open(os.environ["OUTPUT_PATH"], "w", encoding="utf-8") as f:
    json.dump(packages, f, sort_keys=True)
    f.write("\n")

# Build-log only: `installed_total` answers "is this the environment that runs
# the service?", `probed`/`hit` answers "did a sane whitelist arrive?".
print(f"[INFO]: installed_total {len(installed)}, probed {len(wanted)}, hit {len(packages)}")
PYTHON

echo "[INFO]: wrote '${OUTPUT_PATH}'"
cat "${OUTPUT_PATH}"
echo
