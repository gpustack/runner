ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=7.2
ARG VLLM_VERSION=0.27.1

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Give MooncakeConnector the Prometheus registration MultiConnector requires
##
## A MultiConnector asserts that every child which REPORTED transfer statistics is present in its
## Prometheus registry, and it builds that registry from the children whose build_prom_metrics
## returns something other than None. MooncakeConnector reports statistics and inherits the base
## class's None, so pairing it with MooncakeStoreConnector -- which implements both -- makes the
## assertion fire and takes the API server process down. The pair is exactly what a disaggregated
## deployment with a shared KV cache renders, and the assertion needs a SUCCESSFUL transfer to have
## produced the statistics, so it fires when the feature is working.
##
## This fills the gap upstream already marked. vllm/distributed/kv_transfer/kv_connector/v1/
## mooncake/stats.py carries, verbatim:
##
##     # TODO(mooncake-stats): add MooncakePromMetrics (mirror NixlPromMetrics)
##     # and wire it via MooncakeConnector.build_prom_metrics in a follow-up PR.
##
## so the class name and the wiring point are upstream's, not this patch's invention, and
## NixlPromMetrics is the shape it names to mirror.
##
## BOTH EDITS ARE APPENDS. mooncake_connector.py and multi_connector.py differ byte for byte
## between 0.24.0, 0.25.1 and 0.27.1, so an anchored insertion would need a per-version anchor;
## appending needs none. stats.py happens to be identical across the three (sha of the file body
## matches), but it is appended to for the same reason rather than patched in place.

RUN <<EOF
    # Give MooncakeConnector the Prometheus registration MultiConnector requires

    VLLM_DIR="$(python3 -c 'import os, vllm; print(os.path.dirname(vllm.__file__))')"
    MOONCAKE_DIR="${VLLM_DIR}/distributed/kv_transfer/kv_connector/v1/mooncake"

    # Refuse to guess at a layout this patch was not written against.
    test -f "${MOONCAKE_DIR}/stats.py"
    test -f "${MOONCAKE_DIR}/mooncake_connector.py"

    # Idempotent: a re-run over an already patched image must not append twice.
    if grep -q "class MooncakePromMetrics" "${MOONCAKE_DIR}/stats.py"; then
        echo "[info] MooncakePromMetrics is already present; nothing to append."
        exit 0
    fi

    cat >>"${MOONCAKE_DIR}/stats.py" <<'PYEOF'


from vllm.config import VllmConfig
from vllm.distributed.kv_transfer.kv_connector.v1.metrics import (
    KVConnectorPromMetrics,
    PromMetric,
    PromMetricT,
)
from vllm.v1.metrics.utils import create_metric_per_engine


class MooncakePromMetrics(KVConnectorPromMetrics):
    """Prometheus metrics for Mooncake point-to-point KV transfers.

    Mirrors NixlPromMetrics: the histograms take one observation per recorded
    transfer, and the counters take a list of 1s, which is the shape
    MooncakeKVConnectorStats.reset() already produces.

    The metric names are prefixed `vllm:mooncake_` rather than
    `vllm:mooncake_store_`, which MooncakeStorePromMetrics owns: the two
    connectors can be active in the same engine through a MultiConnector, and
    one namespace for both would merge a direct engine-to-engine transfer with
    a round trip to the shared store.
    """

    def __init__(
        self,
        vllm_config: VllmConfig,
        metric_types: dict[type[PromMetric], type[PromMetricT]],
        labelnames: list[str],
        per_engine_labelvalues: dict[int, list[object]],
    ):
        super().__init__(vllm_config, metric_types, labelnames, per_engine_labelvalues)

        duration_buckets = [
            0.001, 0.005, 0.01, 0.025, 0.05, 0.075,
            0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 5.0,
        ]
        histogram_xfer_time = self._histogram_cls(
            name="vllm:mooncake_xfer_time_seconds",
            documentation="Histogram of transfer duration for Mooncake KV cache transfers.",
            buckets=duration_buckets,
            labelnames=labelnames,
        )
        self.histogram_xfer_time = create_metric_per_engine(
            histogram_xfer_time, self.per_engine_labelvalues
        )

        # Uniform 2KiB to 16GiB range, as NixlPromMetrics uses.
        byte_buckets = [2 ** (10 + i) for i in range(1, 25, 2)]
        histogram_bytes_transferred = self._histogram_cls(
            name="vllm:mooncake_bytes_transferred",
            documentation="Histogram of bytes transferred per Mooncake KV cache transfer.",
            buckets=byte_buckets,
            labelnames=labelnames,
        )
        self.histogram_bytes_transferred = create_metric_per_engine(
            histogram_bytes_transferred, self.per_engine_labelvalues
        )

        descriptor_buckets = [10, 20, 30, 50, 75, 100, 200, 300, 500, 750, 1000]
        histogram_num_descriptors = self._histogram_cls(
            name="vllm:mooncake_num_descriptors",
            documentation="Histogram of descriptors per Mooncake KV cache transfer.",
            buckets=descriptor_buckets,
            labelnames=labelnames,
        )
        self.histogram_num_descriptors = create_metric_per_engine(
            histogram_num_descriptors, self.per_engine_labelvalues
        )

        counter_num_failed_transfers = self._counter_cls(
            name="vllm:mooncake_num_failed_transfers",
            documentation="Number of failed Mooncake KV cache transfers.",
            labelnames=labelnames,
        )
        self.counter_num_failed_transfers = create_metric_per_engine(
            counter_num_failed_transfers, self.per_engine_labelvalues
        )

        counter_num_failed_recvs = self._counter_cls(
            name="vllm:mooncake_num_failed_recvs",
            documentation="Number of failed Mooncake KV cache receives.",
            labelnames=labelnames,
        )
        self.counter_num_failed_recvs = create_metric_per_engine(
            counter_num_failed_recvs, self.per_engine_labelvalues
        )

        counter_num_kv_expired_reqs = self._counter_cls(
            name="vllm:mooncake_num_kv_expired_reqs",
            documentation="Number of requests whose Mooncake KV blocks expired.",
            labelnames=labelnames,
        )
        self.counter_num_kv_expired_reqs = create_metric_per_engine(
            counter_num_kv_expired_reqs, self.per_engine_labelvalues
        )

    def observe(self, transfer_stats_data: dict[str, Any], engine_idx: int = 0):
        # A key absent from the payload is skipped rather than raising: the stats
        # container's key set belongs to the connector and may grow or shrink
        # between releases, and a metrics path is the wrong place to fail an engine.
        for prom_obj, key in zip(
            [
                self.histogram_xfer_time,
                self.histogram_bytes_transferred,
                self.histogram_num_descriptors,
            ],
            ["transfer_duration", "bytes_transferred", "num_descriptors"],
        ):
            for list_item in transfer_stats_data.get(key, ()):
                prom_obj[engine_idx].observe(list_item)
        for counter_obj, key in zip(
            [
                self.counter_num_failed_transfers,
                self.counter_num_failed_recvs,
                self.counter_num_kv_expired_reqs,
            ],
            ["num_failed_transfers", "num_failed_recvs", "num_kv_expired_reqs"],
        ):
            for list_item in transfer_stats_data.get(key, ()):
                counter_obj[engine_idx].inc(list_item)
PYEOF

    cat >>"${MOONCAKE_DIR}/mooncake_connector.py" <<'PYEOF'


def _build_mooncake_prom_metrics(
    cls, vllm_config, metric_types, labelnames, per_engine_labelvalues
):
    # Imported here rather than at module scope: this file already imports from
    # .stats, and keeping the dependency inside the call leaves the module's
    # import graph exactly as it was.
    from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.stats import (
        MooncakePromMetrics,
    )

    return MooncakePromMetrics(
        vllm_config, metric_types, labelnames, per_engine_labelvalues
    )


# Bound by assignment rather than written into the class body, so that this patch
# stays an append and needs no anchor inside a file that differs between releases.
MooncakeConnector.build_prom_metrics = classmethod(_build_mooncake_prom_metrics)
PYEOF

    # Assert the patch landed. Both greps are POSITIVE: a negated grep is exempt from
    # set -e, so the inverted form would pass over a failure.
    grep -q "class MooncakePromMetrics" "${MOONCAKE_DIR}/stats.py"
    grep -q "MooncakeConnector.build_prom_metrics = classmethod" "${MOONCAKE_DIR}/mooncake_connector.py"

    # Import it for real. The greps above prove the text is there; this proves it
    # parses and that every name it reaches for resolves in this image.
    python3 -c "
from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.stats import MooncakePromMetrics
from vllm.distributed.kv_transfer.kv_connector.v1.metrics import KVConnectorPromMetrics
assert issubclass(MooncakePromMetrics, KVConnectorPromMetrics)
assert MooncakePromMetrics.observe is not KVConnectorPromMetrics.observe
print('[info] MooncakePromMetrics imports and overrides observe.')
"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
