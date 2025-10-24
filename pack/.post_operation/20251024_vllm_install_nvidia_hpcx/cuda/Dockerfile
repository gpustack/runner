ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.4
ARG VLLM_VERSION=0.10.0
ARG NVIDIA_GDRCOPY_VERSION=2.4.1
ARG NVIDIA_HPCX_VERSION=2.21.3
ARG AWS_EFA_VERSION=1.43.3

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm-build
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install
    apt-get update && apt-get install -y --no-install-recommends \
        libnl-route-3-200 \
        libnl-3-200 \
        libnl-3-dev \
        libnl-route-3-dev \
        libibverbs1 \
        libibverbs-dev \
        librdmacm1 \
        librdmacm-dev \
        libibumad3 \
        libibumad-dev \
        ibverbs-utils \
        ibverbs-providers

    # Prepare
    rm -f $(dpkg-query -L libibverbs-dev librdmacm-dev libibumad-dev | grep "\(\.so\|\.a\)$") || true

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

# Stage vLLM Build GDRCopy
#

FROM vllm-build AS vllm-build-gdrcopy
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ARG NVIDIA_GDRCOPY_VERSION

ENV NVIDIA_GDRCOPY_VERSION=${NVIDIA_GDRCOPY_VERSION}

RUN <<EOF
    # Build GDRCopy

    # Install Dependencies
    apt-get update -y && apt-get install -y --no-install-recommends \
        build-essential \
        devscripts \
        debhelper \
        fakeroot \
        pkg-config \
        dkms

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${NVIDIA_GDRCOPY_VERSION} --single-branch \
        https://github.com/NVIDIA/gdrcopy gdrcopy

    # Build
    pushd /tmp/gdrcopy/packages && \
        CUDA=/usr/local/cuda ./build-deb-packages.sh && \
        tree -hs /tmp/gdrcopy/packages && \
        mv /tmp/gdrcopy/packages /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF


# Stage vLLM
#

FROM vllm-build AS vllm

## Install GDRCopy,
## See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html#nccl-start-base-gdrcopy.

RUN --mount=type=bind,from=vllm-build-gdrcopy,source=/,target=/gdrcopy,rw <<EOF
    # GDRCopy

    if [[ ! -d /gdrcopy/workspace ]]; then
        echo "Skipping GDRCopy installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    dpkg -i /gdrcopy/workspace/libgdrapi_*.deb

    # Review
    ldconfig -v

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install NVIDIA HPC-X,
## See https://catalog.ngc.nvidia.com/orgs/nvidia/containers/cuda-dl-base/layers?version=24.12-cuda12.6-devel-ubuntu24.04.

ARG NVIDIA_HPCX_VERSION

ENV NVIDIA_HPCX_VERSION=${NVIDIA_HPCX_VERSION}

RUN <<EOF
    # NVIDIA HPC-X

    # Prepare
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${CUDA_VERSION}"
    source /etc/os-release

    # Get Download Version
    # If NVIDIA_HPCX_VERSION=2.24.1_cuda13, NVIDIA_HPCX_VERSION_DOWNLOAD=2.24.1
    # If NVIDIA_HPCX_VERSION=2.22.1rc4, NVIDIA_HPCX_VERSION_DOWNLOAD=2.22.1
    # If NVIDIA_HPCX_VERSION=2.21.3, NVIDIA_HPCX_VERSION_DOWNLOAD=2.21.3
    if [[ "${NVIDIA_HPCX_VERSION}" == *"_cuda"* ]]; then
        NVIDIA_HPCX_VERSION_DOWNLOAD=$(echo "${NVIDIA_HPCX_VERSION}" | sed 's/_cuda.*//')
    elif [[ "${NVIDIA_HPCX_VERSION}" == *"rc"* ]]; then
        NVIDIA_HPCX_VERSION_DOWNLOAD=$(echo "${NVIDIA_HPCX_VERSION}" | sed 's/rc.*//')
    else
        NVIDIA_HPCX_VERSION_DOWNLOAD=${NVIDIA_HPCX_VERSION}
    fi

    # Download
    mkdir -p /opt/hpcx
    curl --retry 3 --retry-connrefused -fL "https://content.mellanox.com/hpc/hpc-x/v${NVIDIA_HPCX_VERSION}/hpcx-v${NVIDIA_HPCX_VERSION_DOWNLOAD}-gcc-inbox-${ID}${VERSION_ID}-cuda${CUDA_MAJOR}-$(uname -m).tbz" | tar -jxv -C /opt/hpcx --strip-components 1

    # Install
    ln -sf /opt/hpcx/ompi /usr/local/mpi
    ln -sf /opt/hpcx/ucx /usr/local/ucx
    sed -i 's/^\(hwloc_base_binding_policy\) = core$/\1 = none/' /opt/hpcx/ompi/etc/openmpi-mca-params.conf
    sed -i 's/^\(btl = self\)$/#\1/' /opt/hpcx/ompi/etc/openmpi-mca-params.conf
    cat <<EOT > /etc/ld.so.conf.d/hpcx.conf
/opt/hpcx/clusterkit/lib
/opt/hpcx/hcoll/lib
/opt/hpcx/nccl_rdma_sharp_plugin/lib
/opt/hpcx/ncclnet_plugin/lib
/opt/hpcx/ompi/lib
/opt/hpcx/sharp/lib
/opt/hpcx/ucc/lib
/opt/hpcx/ucx/li
EOT

    # Review
    ldconfig -v

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF
ENV PATH="/usr/local/mpi/bin:/usr/local/ucx/bin:${PATH}" \
    OPAL_PREFIX=/opt/hpcx/ompi \
    OMPI_MCA_coll_hcoll_enable=0

## Install AWS EFA,
## See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html#nccl-start-base-enable.

ARG AWS_EFA_VERSION

ENV AWS_EFA_VERSION=${AWS_EFA_VERSION}

RUN <<EOF
    # AWS EFA

    # Download
    curl --retry 3 --retry-connrefused -fL "https://efa-installer.amazonaws.com/aws-efa-installer-${AWS_EFA_VERSION}.tar.gz" | tar -zxv -C /tmp

    # Install
    pushd /tmp/aws-efa-installer && \
        ./efa_installer.sh -y --skip-kmod

    # Prepare
    rm /opt/amazon/efa/lib/libfabric.a || true

    # Review
    ldconfig -v

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF
ENV PATH="${PATH}:/opt/amazon/efa/bin"

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
