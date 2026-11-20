#!/usr/bin/env bash
set -euo pipefail

# Loopwright command.v1 mounts the check script's parent directory (.auto-sync/checks)
# read-only with whole-tree SHA-256 verification and passes the materialized candidate
# workspace via LOOPWRIGHT_CANDIDATE_DIR (plus baseline snapshot via LOOPWRIGHT_BASE_DIR).
CANDIDATE_DIR="${LOOPWRIGHT_CANDIDATE_DIR:-$PWD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATOR="${SCRIPT_DIR}/validate_candidate.py"
if [[ ! -f "${VALIDATOR}" ]]; then
    echo "missing trusted validator script: ${VALIDATOR}" >&2
    exit 1
fi

# Ensure the offline validator never inherits write-capable GitHub tokens or writes bytecode.
unset GITHUB_TOKEN GH_TOKEN

exec "${PYTHON_BIN:-python3}" -B "${VALIDATOR}" --candidate-dir "${CANDIDATE_DIR}" "$@"
