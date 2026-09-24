ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=7.2
ARG VLLM_VERSION=0.29.0

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Stop MooncakeStoreConnector from saving a load MultiConnector rejected
##
## With MultiConnector(MooncakeConnector, MooncakeStoreConnector) on the decode side, a prompt the
## prefill side has already written to the store is a hit for BOTH children. MultiConnector gives
## the request to MooncakeConnector, which loads asynchronously, and calls the store child with
## zero external tokens, so the store's LoadSpec stays can_load=False. The request is then parked
## waiting for remote KV and scheduled neither as new nor as cached, which routes it into the
## store scheduler's "pending load specs not yet scheduled" branch. That branch passes
## skip_save=None, so the rejected LoadSpec turns into a SAVE job, and _apply_current_save_block_ids
## finds no current block table for a request the core did not schedule:
##
##     AssertionError: Missing current block table for store request ...
##
## EngineCore exits on the first such request. The assertion arrived with upstream #51358, first
## released in 0.29.0; 0.27.1 has the same branch without the assertion.
##
## Upstream fixed it in #54643 (34b1e9f7a6), released in 0.30.0: the branch skips a LoadSpec whose
## load this connector does not own. The hunk below is that change verbatim, rebased onto the 0.29.0
## line numbers. It is also carried into new builds as patches/vllm/003_*.patch.

RUN <<EOF
    # Stop MooncakeStoreConnector from saving a load MultiConnector rejected

    # Locate vLLM without importing it: an import runs vLLM's logging setup, which
    # writes to stdout and would end up inside the captured path.
    VLLM_SITE="$(python3 -c 'import importlib.util, os; print(os.path.dirname(os.path.dirname(importlib.util.find_spec("vllm").origin)))')"
    SCHEDULER="${VLLM_SITE}/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py"

    # Refuse to guess at a layout this patch was not written against.
    test -f "${SCHEDULER}"

    # Idempotent: an image that already carries the fix is left alone.
    if grep -q "if load_spec is None or not load_spec.can_load:" "${SCHEDULER}"; then
        echo "[info] The pending-load branch already skips rejected load specs; nothing to patch."
        exit 0
    fi

    pushd "${VLLM_SITE}"
    patch -p1 <<'PATCHEOF'
diff --git a/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py b/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py
--- a/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py
+++ b/vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py
@@ -371,7 +371,12 @@
         ) in self._unfinished_requests.items():
             if request_id not in request_ids and request_id not in cached_reqs.req_ids:
                 load_spec = self.load_specs.pop(request_id, None)
-                if not load_spec:
+                # A load spec may have been proposed by this connector's
+                # lookup but rejected by MultiConnector in favor of another
+                # connector. Only the chosen connector may issue the pending
+                # load; the normal store path gets its blocks later from
+                # SchedulerOutput once the request is actually scheduled.
+                if load_spec is None or not load_spec.can_load:
                     continue
                 num_tokens_to_compute = load_spec.kvpool_cached_tokens
                 request_tracker = RequestTracker(
PATCHEOF
    popd

    # Assert the patch landed. The grep is POSITIVE: a negated grep is exempt from
    # set -e, so the inverted form would pass over a failure.
    grep -q "if load_spec is None or not load_spec.can_load:" "${SCHEDULER}"

    # Import it for real: the grep proves the text is there, this proves it parses.
    python3 -c "
from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.scheduler import MooncakeStoreScheduler
print('[info] MooncakeStoreScheduler imports.')
"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Probe Dependencies

ARG DEPENDENCY_PACKAGES=""
RUN --mount=type=bind,from=shared,source=probe_dependencies.sh,target=/tmp/probe_dependencies.sh \
    DEPENDENCY_PACKAGES="${DEPENDENCY_PACKAGES}" bash /tmp/probe_dependencies.sh

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

## Export Dependencies

FROM scratch AS vllm-deps

COPY --from=vllm /etc/gpustack-runner/dependencies.json /
