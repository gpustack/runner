ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.4
ARG VLLM_VERSION=0.10.0

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH


## Polish NVIDIA HPC-X

RUN <<EOF
    # NVIDIA HPC-X

    # Polish
    cat <<EOT > /etc/ld.so.conf.d/hpcx.conf
/opt/hpcx/clusterkit/lib
/opt/hpcx/hcoll/lib
/opt/hpcx/nccl_rdma_sharp_plugin/lib
/opt/hpcx/ncclnet_plugin/lib
/opt/hpcx/ompi/lib
/opt/hpcx/sharp/lib
/opt/hpcx/ucc/lib
/opt/hpcx/ucx/lib
EOT

    # Review
    ldconfig -v
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
