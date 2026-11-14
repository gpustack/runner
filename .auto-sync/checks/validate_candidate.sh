#!/usr/bin/env bash
set -euo pipefail

# Loopwright's startLocalCommandGateServer copies validate_candidate.sh to ${workDir}/gate-script.sh
# and materializes the baseline tree plus candidate overlay at ${CANDIDATE_DIR}.
# Use SCRIPT_DIR for direct CLI runs and fall back to CANDIDATE_DIR when staged as gate-script.sh.
CANDIDATE_DIR="${LOOPWRIGHT_CANDIDATE_DIR:-$PWD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/validate_candidate.py" ]]; then
    VALIDATOR="${SCRIPT_DIR}/validate_candidate.py"
else
    VALIDATOR="${CANDIDATE_DIR}/.auto-sync/checks/validate_candidate.py"
fi

# Ensure the offline validator never inherits write-capable GitHub tokens.
unset GITHUB_TOKEN GH_TOKEN

exec "${PYTHON_BIN:-python3}" "${VALIDATOR}" --candidate-dir "${CANDIDATE_DIR}" "$@"
