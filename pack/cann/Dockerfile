# Package logic:
# 1. runtime target:
#    - Install tools.
#    - Upgrade GCC if needed.
#    - Install C buildkit.
#    - Upgrade Python if needed.
#    - Install Python buildkit.
#    - Install CANN buildkit if needed.
# 2. mindie target.
#    - Install Torch.
#    - Install MindIE.
#    - Install dependencies.
#    - Postprocess, review installation.
# 3. vllm target.
#    - Install Torch.
#    - Install vLLM from source.
#    - Install vLLM-Ascend from source.
#    - Install dependencies.
#    - Postprocess, review installation.
# 5. sglang target.
#    - Build SGLang from source (Ascend/NPU), including sgl-kernel-npu and deep-ep.
#    - Install sglang with NPU extras.
#    - Ecosystem install: MemFabric and Triton Ascend.
#    - Optional: Install BiSheng toolkit.
#    - Postprocess, review installation.

# Argument usage:
# - PYTHON_VERSION: Version of Python to use.
# - CMAKE_MAX_JOBS: Maximum number of jobs to use for CMake,
#   if not specified, it will be set automatically based on the number of CPU cores.
# - CANN_VERSION: Version of Ascend CANN runtime environment to use.
# - CANN_ARCHS: Arch variant list supports for this runtime environment,
#   it only support one architecture at present, eg. 310p, 910b and a3.
# - MINDIE_BASE_IMAGE: Base image for MindIE.
# - MINDIE_VERSION: Version of MindIE to use.
# - MINDIE_TORCH_VERSION: Version of Torch for MindIE to use.
# - VLLM_BASE_IMAGE: Base image for vLLM.
# - VLLM_VERSION: Version of vLLM to use.
# - VLLM_ASCEND_VERSION: Version of vLLM Ascend to use,
#   if not specified, it will fetch from the vLLM Ascend PyPi RSS.
# - VLLM_TORCH_VERSION: Version of Torch for vLLM to use.
# - SGLANG_VERSION: Version of SGLang to use.

ARG PYTHON_VERSION=3.11
ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.2.rc2
ARG CANN_ARCHS=910b
ARG MINDIE_BASE_IMAGE=gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-python${PYTHON_VERSION}
ARG MINDIE_VERSION=2.1.rc2
ARG MINDIE_TORCH_VERSION=2.1.0
ARG VLLM_BASE_IMAGE=gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.11.0
ARG VLLM_ASCEND_VERSION
ARG VLLM_TORCH_VERSION=2.7.1

#
# Stage Bake Runtime
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-${CANN_ARCHS}-python${PYTHON_VERSION}-linux-amd64 --target=runtime pack/cann
#

FROM quay.io/ascend/cann:${CANN_VERSION}-${CANN_ARCHS}-ubuntu22.04-py${PYTHON_VERSION} AS runtime
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Tools

ENV DEBIAN_FRONTEND=noninteractive \
    LANG='en_US.UTF-8' \
    LANGUAGE='en_US:en' \
    LC_ALL='en_US.UTF-8'

RUN <<EOF
    # Tools

    # Refresh
    apt-get update -y && apt-get install -y --no-install-recommends \
        software-properties-common apt-transport-https \
        ca-certificates gnupg2 lsb-release gnupg-agent \
      && apt-get update -y \
      && add-apt-repository -y ppa:ubuntu-toolchain-r/test \
      && apt-get update -y

    # Install
    apt-get install -y --no-install-recommends \
        ca-certificates build-essential binutils bash openssl \
        curl wget aria2 \
        git git-lfs \
        unzip xz-utils \
        tzdata locales \
        iproute2 iputils-ping ifstat net-tools dnsutils pciutils ipmitool \
        procps sysstat htop \
        tini vim jq bc tree

    # Update locale
    localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8

    # Update timezone
    rm -f /etc/localtime \
        && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
        && echo "Asia/Shanghai" > /etc/timezone \
        && dpkg-reconfigure --frontend noninteractive tzdata

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Upgrade GCC if needed

RUN <<EOF
    # GCC

    # Upgrade GCC if the Ubuntu version is lower than 21.04.
    source /etc/os-release
    if (( $(echo "${VERSION_ID} >= 21.04" | bc -l) )); then
        echo "Skipping GCC upgrade for ${VERSION_ID}..."
        exit 0
    fi

    # Install
    apt-get install -y --no-install-recommends \
        gcc-11 g++-11 gfortran-11 gfortran

    # Update alternatives
    if [[ -f /etc/alternatives/gcov-dump ]]; then update-alternatives --remove-all gcov-dump; fi; update-alternatives --install /usr/bin/gcov-dump gcov-dump /usr/bin/gcov-dump-11 10
    if [[ -f /etc/alternatives/lto-dump ]]; then update-alternatives --remove-all lto-dump; fi; update-alternatives --install /usr/bin/lto-dump lto-dump /usr/bin/lto-dump-11 10
    if [[ -f /etc/alternatives/gcov ]]; then update-alternatives --remove-all gcov; fi; update-alternatives --install /usr/bin/gcov gcov /usr/bin/gcov-11 10
    if [[ -f /etc/alternatives/gcc ]]; then update-alternatives --remove-all gcc; fi; update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 10
    if [[ -f /etc/alternatives/gcc-nm ]]; then update-alternatives --remove-all gcc-nm; fi; update-alternatives --install /usr/bin/gcc-nm gcc-nm /usr/bin/gcc-nm-11 10
    if [[ -f /etc/alternatives/cpp ]]; then update-alternatives --remove-all cpp; fi; update-alternatives --install /usr/bin/cpp cpp /usr/bin/cpp-11 10
    if [[ -f /etc/alternatives/g++ ]]; then update-alternatives --remove-all g++; fi; update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-11 10
    if [[ -f /etc/alternatives/gcc-ar ]]; then update-alternatives --remove-all gcc-ar; fi; update-alternatives --install /usr/bin/gcc-ar gcc-ar /usr/bin/gcc-ar-11 10
    if [[ -f /etc/alternatives/gcov-tool ]]; then update-alternatives --remove-all gcov-tool; fi; update-alternatives --install /usr/bin/gcov-tool gcov-tool /usr/bin/gcov-tool-11 10
    if [[ -f /etc/alternatives/gcc-ranlib ]]; then update-alternatives --remove-all gcc-ranlib; fi; update-alternatives --install /usr/bin/gcc-ranlib gcc-ranlib /usr/bin/gcc-ranlib-11 10
    if [[ -f /etc/alternatives/gfortran ]]; then update-alternatives --remove-all gfortran; fi; update-alternatives --install /usr/bin/gfortran gfortran /usr/bin/gfortran-11 10

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install C buildkit

RUN <<EOF
    # C buildkit

    # Install
    apt-get install -y --no-install-recommends \
        make ninja-build pkg-config ccache
    curl --retry 3 --retry-connrefused -fL "https://github.com/Kitware/CMake/releases/download/v3.31.7/cmake-3.31.7-linux-$(uname -m).tar.gz" | tar -zx -C /usr --strip-components 1

    # Install dependencies
    apt-get install -y --no-install-recommends \
        perl-openssl-defaults perl yasm \
        zlib1g zlib1g-dev libbz2-dev libffi-dev libgdbm-dev libgdbm-compat-dev \
        openssl libssl-dev libsqlite3-dev lcov libomp-dev \
        libblas-dev liblapack-dev libopenblas-dev libblas3 liblapack3 libhdf5-dev \
        libxml2 libxslt1-dev libgl1-mesa-glx libgmpxx4ldbl \
        libncurses5-dev libreadline6-dev libsqlite3-dev \
        liblzma-dev lzma lzma-dev tk-dev uuid-dev libmpdec-dev \
        ffmpeg libjpeg-dev libpng-dev libtiff-dev libwebp-dev \
        libnuma-dev libjemalloc-dev

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Upgrade Python if needed

ARG PYTHON_VERSION

ENV PYTHON_VERSION=${PYTHON_VERSION}

RUN <<EOF
    # Python

    if (( $(echo "$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2) == ${PYTHON_VERSION}" | bc -l) )); then
        echo "Skipping Python upgrade for ${PYTHON_VERSION}..."
        if [[ -z "$(ldconfig -v 2>/dev/null | grep libpython${PYTHON_VERSION})" ]]; then
            PYTHON_LIB_PREFIX=$(python3 -c "import sys; print(sys.base_prefix);")
            echo "${PYTHON_LIB_PREFIX}/lib" >> /etc/ld.so.conf.d/python3.conf
            echo "${PYTHON_LIB_PREFIX}/lib64" >> /etc/ld.so.conf.d/python3.conf
            EXPORT_PYTHON_LIB="export LD_LIBRARY_PATH=${PYTHON_LIB_PREFIX}/lib:${PYTHON_LIB_PREFIX}/lib64:\${LD_LIBRARY_PATH}"
            echo "${EXPORT_PYTHON_LIB}" >> /etc/profile
            echo "${EXPORT_PYTHON_LIB}" >> ~/.bashrc
        fi
        exit 0
    fi

    # Add deadsnakes PPA for Python versions
    for i in 1 2 3; do
        add-apt-repository -y ppa:deadsnakes/ppa && break || { echo "Attempt $i failed, retrying in 5s..."; sleep 5; }
    done
    apt-get update -y

    # Install
    apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-dev \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-distutils \
        python${PYTHON_VERSION}-lib2to3 \
        python${PYTHON_VERSION}-gdbm \
        python${PYTHON_VERSION}-tk \
        libibverbs-dev

    # Update alternatives
    if [[ -f /etc/alternatives/python3 ]]; then update-alternatives --remove-all python3; fi; update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1
    if [[ -f /etc/alternatives/python ]]; then update-alternatives --remove-all python; fi; update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1
    curl -sS "https://bootstrap.pypa.io/get-pip.py" | python${PYTHON_VERSION}
    if [[ -f /etc/alternatives/2to3 ]]; then update-alternatives --remove-all 2to3; fi; update-alternatives --install /usr/bin/2to3 2to3 /usr/bin/2to3${PYTHON_VERSION} 1 || true
    if [[ -f /etc/alternatives/pydoc3 ]]; then update-alternatives --remove-all pydoc3; fi; update-alternatives --install /usr/bin/pydoc3 pydoc3 /usr/bin/pydoc${PYTHON_VERSION} 1 || true
    if [[ -f /etc/alternatives/idle3 ]]; then update-alternatives --remove-all idle3; fi; update-alternatives --install /usr/bin/idle3 idle3 /usr/bin/idle${PYTHON_VERSION} 1 || true
    if [[ -f /etc/alternatives/python3-config ]]; then update-alternatives --remove-all python3-config; fi; update-alternatives --install /usr/bin/python3-config python3-config /usr/bin/python${PYTHON_VERSION}-config 1 || true

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install Python buildkit

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIPX_HOME=/root/.local/share/pipx \
    PIPX_LOCAL_VENVS=/root/.local/share/pipx/venvs \
    UV_NO_CACHE=1 \
    UV_HTTP_TIMEOUT=500 \
    UV_INDEX_STRATEGY="unsafe-best-match"

RUN <<EOF
    # Buildkit

    cat <<EOT >/tmp/requirements.txt
build
cmake<4
ninja<1.11
setuptools<80
setuptools-scm
packaging<25
wheel
pybind11<3
Cython
psutil
pipx
uv
EOT
    pip install -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install CANN buildkit if needed

ARG CANN_VERSION
ARG CANN_ARCHS

ENV CANN_HOME="/usr/local/Ascend" \
    CANN_VERSION=${CANN_VERSION} \
    CANN_ARCHS=${CANN_ARCHS}

RUN <<EOF
    # CANN Toolkit

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${CANN_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"

    if [[ -d "${CANN_HOME}/ascend-toolkit/${DOWNLOAD_VERSION}" ]]; then
        echo "Skipping CANN Toolkit upgrade for ${DOWNLOAD_VERSION}..."
        exit 0
    fi

    # Install dependencies
    cat <<EOT >/tmp/requirements.txt
attrs==24.3.0
numpy==1.26.4
decorator==5.2.1
sympy==1.14.0
cffi==1.17.1
PyYAML==6.0.2
pathlib2==2.3.7.post1
protobuf==6.31.0
scipy==1.15.3
requests==2.32.3
absl-py==2.2.2
EOT
    pip install -r /tmp/requirements.txt

    # Install toolkit
    TOOLKIT_FILE="Ascend-cann-toolkit_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    TOOLKIT_PATH="/tmp/${TOOLKIT_FILE}"
    TOOLKIT_URL="${URL_PREFIX}/${TOOLKIT_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${TOOLKIT_PATH}" "${TOOLKIT_URL}"
    chmod a+x "${TOOLKIT_PATH}"
    printf "Y\n" | "${TOOLKIT_PATH}" --install --install-for-all --install-path="${CANN_HOME}"

    # Cleanup
   rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt \
        && rm -rf /var/log/ascend \
        && rm -rf /var/log/ascend_seclog
EOF

RUN <<EOF
    # CANN Kernels

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${CANN_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"

    if [[ -d "${CANN_HOME}/ascend-toolkit/${DOWNLOAD_VERSION}" ]]; then
        echo "Skipping CANN Kernels upgrade for ${DOWNLOAD_VERSION}..."
        exit 0
    fi

    # Prepare environment
    source ${CANN_HOME}/ascend-toolkit/set_env.sh

    # Install kernels
    KERNELS_FILE="Ascend-cann-kernels-${CANN_ARCHS}_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    if ! curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fsSIL "${URL_PREFIX}/${KERNELS_FILE}?${URL_SUFFIX}" >/dev/null 2>&1; then
        # Fallback to generic kernels
        KERNELS_FILE="Ascend-cann-kernels-${CANN_ARCHS}_${DOWNLOAD_VERSION}_${OS}.run"
    fi
    KERNELS_PATH="/tmp/${KERNELS_FILE}"
    KERNELS_URL="${URL_PREFIX}/${KERNELS_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${KERNELS_PATH}" "${KERNELS_URL}"
    chmod a+x "${KERNELS_PATH}"
    printf "Y\n" |"${KERNELS_PATH}" --install --install-for-all --install-path="${CANN_HOME}"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt \
        && rm -rf /var/log/ascend \
        && rm -rf /var/log/ascend_seclog
EOF

RUN <<EOF
    # CANN NNAL

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${CANN_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"

    if [[ -d "${CANN_HOME}/ascend-toolkit/${DOWNLOAD_VERSION}" ]] && [[ -d "${CANN_HOME}/nnal" ]]; then
        echo "Skipping CANN NNAL upgrade for ${DOWNLOAD_VERSION}..."
        exit 0
    fi

    # Prepare environment
    source ${CANN_HOME}/ascend-toolkit/set_env.sh

    # Install NNAL
    NNAL_FILE="Ascend-cann-nnal_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    NNAL_PATH="/tmp/${NNAL_FILE}"
    NNAL_URL="${URL_PREFIX}/${NNAL_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${NNAL_PATH}" "${NNAL_URL}"
    chmod a+x "${NNAL_PATH}"
    printf "Y\n" | "${NNAL_PATH}" --install --install-path="${CANN_HOME}"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt \
        && rm -rf /var/log/ascend_seclog \
        && rm -rf /var/log/cann_atb_log
EOF

## Declare Environment

ENV PATH="${CANN_HOME}/driver/tools:${PATH}"

# Stage Install MindIE
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-mindie{MINDIE_VERSION}-linux-arm64 --target=mindie pack/cann
#

FROM ${MINDIE_BASE_IMAGE} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Torch

ARG MINDIE_TORCH_VERSION

ENV MINDIE_TORCH_VERSION=${MINDIE_TORCH_VERSION}

RUN <<EOF
    # Torch

    # Install Torch
    cat <<EOT >/tmp/requirements.txt
torch==${MINDIE_TORCH_VERSION}
torchvision
torchaudio
EOT
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    else
        uv pip install \
            -r /tmp/requirements.txt
    fi
    uv pip install \
        torch-npu==${MINDIE_TORCH_VERSION}.*

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install MindIE

ARG MINDIE_VERSION

ENV MINDIE_VERSION=${MINDIE_VERSION}

ADD --chown=root:root mindie-atb-models_${MINDIE_VERSION}_${TARGETOS}-${TARGETARCH}_py${PYTHON_VERSION}_torch${MINDIE_TORCH_VERSION}-abi0.tar.gz ${CANN_HOME}/atb-models/
RUN <<EOF
    # MindIE

    # Install dependencies
    cat <<EOT >/tmp/requirements.txt
absl-py==2.2.2
accelerate==0.34.2
aiohappyeyeballs==2.6.1
aiohttp==3.12.15
aiosignal==1.4.0
attrs==24.3.0
certifi==2024.8.30
cloudpickle==3.0.0
cpm-kernels==1.0.11
decorator==5.2.1
easydict==1.13
einops==0.8.1
et-xmlfile==1.1.0
frozenlist==1.7.0
fuzzywuzzy==0.18.0
gevent==24.2.1
geventhttpclient==2.3.1
greenlet==3.2.1
grpcio==1.71.0
icetk==0.0.4
idna==2.8
jieba==0.42.1
Jinja2==3.1.6
jiter==0.11.0
joblib==1.4.2
json5==0.12.1
jsonlines==4.0.0
jsonschema==4.23.0
latex2mathml==3.77.0
loguru==0.7.2
Markdown==3.7
matplotlib==3.9.2
mdtex2html==1.3.0
ml_dtypes==0.5.0
multidict==6.4.3
nltk==3.9.1
numba==0.61.2
numpy==1.26.4
onnx==1.19.0
openai==1.108.1
opencv-python-headless==4.11.0.86
openpyxl==3.1.5
orjson==3.11.3
pandas==2.2.3
pillow==11.2.1
prettytable==3.11.0
propcache==0.3.1
psutil==7.0.0
pyarrow==19.0.1
pydantic_core==2.23.4
pydantic==2.9.2
python-rapidjson==1.20
requests==2.32.3
rouge-score==0.1.2
rouge==1.0.1
sacrebleu==2.4.3
scipy==1.15.3
text-generation==0.7.0
thefuzz==0.22.1
tiktoken==0.7.0
tornado==6.4.2
tqdm==4.67.1
transformers==4.46.3
safetensors==0.5.3
tritonclient==2.49.0
typing_extensions==4.13.2
tzdata==2024.2
urllib3==2.4.0
yarl==1.20.1
zope.event==5.0
zope.interface==7.0.3
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Install ATB models
    uv pip install \
        ${CANN_HOME}/atb-models/*.whl

    # Install MindIE
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${MINDIE_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/MindIE/MindIE%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"
    MINDIE_FILE="Ascend-mindie_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    IFS="." read -r MINDIE_MAJOR MINDIE_MINOR MINDIE_PATCH <<< "${MINDIE_VERSION}"
    if (( $(echo "${MINDIE_MAJOR}.${MINDIE_MINOR} >= 2.1" | bc -l) )); then
        MINDIE_FILE="Ascend-mindie_${DOWNLOAD_VERSION}_${OS}-${ARCH}_abi0.run"
    fi
    MINDIE_PATH="/tmp/${MINDIE_FILE}"
    MINDIE_URL="${URL_PREFIX}/${MINDIE_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${MINDIE_PATH}" "${MINDIE_URL}"
    chmod a+x "${MINDIE_PATH}"
    printf "Y\n" | "${MINDIE_PATH}" --install --install-path="${CANN_HOME}"

    # Fix
    # - Make MindIE service configuration writable.
    chmod +w "${CANN_HOME}/mindie/latest/mindie-service/conf"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess

RUN <<EOF
    # Postprocess

    # Hijack executable path
    PYTHON_LIB_PREFIX=$(python3 -c "import sys; print(sys.base_prefix);")
    mv ${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon ${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon_
    cat <<EOT >${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon
#!/usr/bin/bash

source \${CANN_HOME}/ascend-toolkit/set_env.sh
source \${CANN_HOME}/nnal/atb/set_env.sh
source \${CANN_HOME}/atb-models/set_env.sh

export LD_LIBRARY_PATH=${PYTHON_LIB_PREFIX}/lib:${PYTHON_LIB_PREFIX}/lib64:\${LD_LIBRARY_PATH}

exec \${BASH_SOURCE[0]}_ "\$@"
EOT
    chmod a+x ${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon

    # Review
    uv pip tree
EOF

## Entrypoint

ENV PATH="${CANN_HOME}/mindie/latest/mindie-service/bin:${PATH}"

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage Install vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-vllm${VLLM_VERSION}-linux-arm64 --target=vllm pack/cann
#

FROM ${VLLM_BASE_IMAGE} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Torch

ARG VLLM_TORCH_VERSION

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION}

RUN <<EOF
    # Torch

    # Install Torch
    cat <<EOT >/tmp/requirements.txt
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    else
        uv pip install \
            -r /tmp/requirements.txt
    fi
    uv pip install --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi \
        torch-npu==${VLLM_TORCH_VERSION}.*
    uv pip install \
        numpy spicy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install vLLM

ARG CMAKE_MAX_JOBS
ARG VLLM_VERSION
ARG VLLM_ASCEND_VERSION

ENV VLLM_VERSION=${VLLM_VERSION} \
    VLLM_ASCEND_VERSION=${VLLM_ASCEND_VERSION}

RUN <<EOF
    # vLLM

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/local/Ascend/ascend-toolkit/latest/$(uname -i)-linux/devlib"

    # Install vLLM
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_VERSION} --single-branch \
        https://github.com/vllm-project/vllm.git vllm-${VLLM_VERSION}
    VLLM_TARGET_DEVICE="empty" uv pip install --verbose /tmp/vllm-${VLLM_VERSION} --extra-index-url https://download.pytorch.org/whl/cpu/
    # Fix
    # - vLLM Ascend doesn't support triton, uninstall it.
    uv pip uninstall triton || true

    # Install vLLM Ascend
    VLLM_ASCEND_VERSION=${VLLM_ASCEND_VERSION:-}
    if [[ -z "${VLLM_ASCEND_VERSION}" ]]; then
        # Fetch the latest version from RSS subscription.
        VLLM_ASCEND_VERSION="$(curl -sS https://pypi.org/rss/project/vllm-ascend/releases.xml | grep title | grep "${VLLM_VERSION}" | head -n 1 | awk -F '[<>]' '/<title>/ {print $3}')"
    fi
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_ASCEND_VERSION} --single-branch \
        https://github.com/vllm-project/vllm-ascend.git vllm-ascend-${VLLM_ASCEND_VERSION}
    VLLM_TARGET_DEVICE="empty" pip install -v /tmp/vllm-ascend-${VLLM_ASCEND_VERSION} --extra-index-url https://download.pytorch.org/whl/cpu/ --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi
    # Fix
    # - Replace SoC version instead of compile.
    if [[ "${CANN_ARCHS}" == "310p" ]]; then
        sed -i "s/^__soc_version__.*/__soc_version__ = 'ASCEND310P3'/" $(pip show vllm-ascend | grep Location: | cut -d':' -f 2)/vllm_ascend/_build_info.py
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install
    cat <<EOT >/tmp/requirements.txt
accelerate
hf_transfer
modelscope
ray[client]>=2.47.1,<=2.48.0
ray[default]>=2.47.1,<=2.48.0
protobuf>3.20.0
grpcio==1.71.0
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess

RUN <<EOF
    # Postprocess

    # Hijack executable path
    PYTHON_LIB_PREFIX=$(python3 -c "import sys; print(sys.base_prefix);")
    mv ${PYTHON_LIB_PREFIX}/bin/vllm ${PYTHON_LIB_PREFIX}/bin/vllm_
    cat <<EOT >${PYTHON_LIB_PREFIX}/bin/vllm
#!/usr/bin/bash

source \${CANN_HOME}/ascend-toolkit/set_env.sh
source \${CANN_HOME}/nnal/atb/set_env.sh

export LD_LIBRARY_PATH=${PYTHON_LIB_PREFIX}/lib:${PYTHON_LIB_PREFIX}/lib64:\${LD_LIBRARY_PATH}

exec \${BASH_SOURCE[0]}_ "\$@"
EOT
    chmod a+x ${PYTHON_LIB_PREFIX}/bin/vllm

    # Review
    uv pip tree \
        --package vllm \
        --package vllm-ascend \
        --package torch \
        --package torch-npu
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_ASCEND_RT_VISIBLE_DEVICES=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage SGLang (inherits vLLM)
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 \
#     --file=test/testDockerfile.cann \
#     --tag=gpustack/runner:cann${CANN_VERSION%.*}-sglang-linux-arm64 \
#     --target=sglang test
#
FROM vllm AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Build args for SGLang
ARG SGL_REPO="https://github.com/sgl-project/sglang.git"
ARG SGL_DEFAULT="main"
ARG SGL_BRANCH=${SGL_DEFAULT}
ARG BUILD_TYPE=srt
ARG NO_DEPS_FLAG=""
ARG SGLANG_VERSION=0.5.3.post3
ENV SGLANG_VERSION=${SGLANG_VERSION}

## Build args for sgl-kernel-npu
ARG SGL_KERNEL_NPU_REPO="https://github.com/sgl-project/sgl-kernel-npu.git"
ARG SGL_KERNEL_NPU_BRANCH=${SGL_DEFAULT}
## NPU ecosystem components
ARG MEMFABRIC_URL="https://sglang-ascend.obs.cn-east-3.myhuaweicloud.com/sglang/mf_adapter-1.0.0-cp311-cp311-linux_aarch64.whl"
ARG TRITON_ASCEND_URL="https://sglang-ascend.obs.cn-east-3.myhuaweicloud.com/sglang/triton_ascend-3.2.0%2Bgitb0ea0850-cp311-cp311-linux_aarch64.whl"
ARG BISHENG_URL="https://sglang-ascend.obs.cn-east-3.myhuaweicloud.com/sglang/Ascend-BiSheng-toolkit_aarch64.run"

## Ascend toolkit path
ENV ASCEND_CANN_PATH="${CANN_HOME}/ascend-toolkit"

## Install SGLang and NPU components
RUN <<EOF
    # Prepare Python build deps and utilities
    uv pip install --verbose wheel build IPython orjson python-multipart pybind11

    # Clean any previous installs
    pip uninstall -y sgl_kernel_npu deep-ep sglang || true

    # Ecosystem: MemFabric and Triton Ascend
    uv pip install --no-cache-dir wheel==0.45.1
    uv pip install --no-cache-dir ${MEMFABRIC_URL}
    uv pip install --no-cache-dir ${TRITON_ASCEND_URL}

    # Clone SGLang and install Python package (NPU extras)
    mkdir -p /sgl-workspace && pushd /sgl-workspace
    git clone ${SGL_REPO}
    cd sglang
    # Prefer version tag if provided, otherwise fall back to branch selection
    if [[ -n "${SGLANG_VERSION}" ]]; then
      git fetch --tags --depth=1
      if git rev-parse -q --verify "refs/tags/v${SGLANG_VERSION}" >/dev/null; then
        echo "Checking out tag v${SGLANG_VERSION}"; git checkout -q "tags/v${SGLANG_VERSION}"
      elif git rev-parse -q --verify "refs/tags/${SGLANG_VERSION}" >/dev/null; then
        echo "Checking out tag ${SGLANG_VERSION}"; git checkout -q "tags/${SGLANG_VERSION}"
      elif git rev-parse -q --verify "${SGLANG_VERSION}" >/dev/null; then
        echo "Checking out commit/branch ${SGLANG_VERSION}"; git checkout -q "${SGLANG_VERSION}"
      elif [[ "${SGL_BRANCH}" != "${SGL_DEFAULT}" ]]; then
        echo "Checking out branch ${SGL_BRANCH}"; git checkout -q "${SGL_BRANCH}"
      else
        echo "Using ${SGL_DEFAULT} default branch"
      fi
    else
      if [[ "${SGL_BRANCH}" != "${SGL_DEFAULT}" ]]; then
        echo "Checking out branch ${SGL_BRANCH}"; git checkout -q "${SGL_BRANCH}"
      fi
    fi
    rm -f python/pyproject.toml
    mv python/pyproject_other.toml python/pyproject.toml
    if [[ "${BUILD_TYPE}" == "srt" ]]; then
      python -m pip --no-cache-dir install -e "python[srt_npu]" ${NO_DEPS_FLAG}
    else
      python -m pip --no-cache-dir install -e "python[all_npu]" ${NO_DEPS_FLAG}
    fi
    popd

    # Build sgl-kernel-npu and deep-ep wheels
    git -C /sgl-workspace clone --depth 1 ${SGL_KERNEL_NPU_REPO} ${SGL_KERNEL_NPU_BRANCH:+--branch ${SGL_KERNEL_NPU_BRANCH}}
    export LD_LIBRARY_PATH=${ASCEND_CANN_PATH}/latest/runtime/lib64/stub:$LD_LIBRARY_PATH
    source ${ASCEND_CANN_PATH}/set_env.sh
    pushd /sgl-workspace/sgl-kernel-npu
    bash build.sh
    pip install output/deep_ep*.whl output/sgl_kernel_npu*.whl --no-cache-dir
    popd

    # Link deep_ep cpp .so to package root for runtime discovery
    cd "$(pip show deep-ep | awk '/^Location:/ {print $2}')" && ln -sf deep_ep/deep_ep_cpp*.so .

    # Install BiSheng toolkit (Ascend)
    wget ${BISHENG_URL} && chmod a+x Ascend-BiSheng-toolkit_aarch64.run && ./Ascend-BiSheng-toolkit_aarch64.run --install && rm Ascend-BiSheng-toolkit_aarch64.run

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess review
RUN <<EOF
    uv pip tree \
        --package sglang \
        --package torch \
        --package torch-npu \
        --package deep-ep
EOF

## Performance environment variables
ENV PYTORCH_NPU_ALLOC_CONF=expandable_segments:True \
    SGLANG_SET_CPU_AFFINITY=1 \
    SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1 \
    HCCL_BUFFSIZE=200 \
    SGLANG_NPU_USE_MLAPO=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
