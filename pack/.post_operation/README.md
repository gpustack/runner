# Post Profile of GPUStack Runner

Normally, images are immutable.
However, for some needs, we have to modify the image's content while preserving its tag.

> [!CAUTION]
> - This behavior is **DANGEROUS** and **NOT RECOMMENDED**.
> - This behavior is **NOT IDEMPOTENT** and therefore **CANNOT BE REVERSED** after released.

We leverage the matrix expansion feature of GPUStack Runner to achieve this, and document here the operations we perform.

## Requirements for a New Operation

`gpustack_runner/runner.py.json` records, per tag, the versions of the whitelisted
packages that the image ships. An operation rewrites the content behind an already
released tag, so one that touches the Python environment without probing it again
leaves those versions describing the image as it was *before* the operation.

Every **new** operation's Dockerfile must therefore end with the dependency probe and
expose the export stage. Copy the shape verbatim from `pack/<backend>/Dockerfile*`:

```dockerfile
FROM gpustack/runner:<released-tag> AS vllm

# ... the operation itself ...

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
```

Replace `vllm` with the service target of the operation. The export stage name must be
exactly `<service>-deps`: `pack.yml` skips the export when it cannot find that stage,
so a misspelled name silently ships without refreshing the recorded versions.
`probe_dependencies.sh` arrives through the named build context `shared`, which
`pack.yml` supplies for post operations too, so nothing else needs wiring up.

Running such an operation:

- Run it with `for_release=true`. Otherwise every tag carries the `-dev` suffix and
  addresses no released entry.
- `merge_runner.sh` then **only updates the `dependencies` of the entries that already
  exist**; it never adds an entry, and never touches any other field. A probed tag that
  does not address exactly one existing entry fails the job, printing the `platform`,
  `docker_image` and `platform_tag` it looked for.
- The run opens the usual `chore: update runner` pull request, which also regenerates
  `tests/gpustack_runner/fixtures/`. A fixture diff unrelated to the operation is
  therefore possible and not, by itself, a sign that something went wrong.

The operations recorded below predate this requirement and are deliberately left
unchanged. They do not refresh `dependencies`: the recorded versions for the tags they
mutated stay as they were until the next release rebuilds those images.

- [x] 2025-10-20: Install `lmcache` package for CANN/CUDA/ROCm released images.
- [x] 2025-10-22: Install `ray[client]` package for CANN/CUDA/ROCm released images.
- [x] 2025-10-22: Install `ray[default]` package for CUDA/ROCm released images.
- [x] 2025-10-22: Reinstall `lmcache` package for CUDA released images.
- [x] 2025-10-24: Install NVIDIA HPC-X suit for CUDA released images.
- [x] 2025-10-29: Reinstall `ray[client] ray[default]` packages for CANN released images.
- [x] 2025-11-03: Refresh MindIE entrypoint for CANN released images.
- [x] 2025-11-05: Polish NVIDIA HPC-X configuration for CUDA released images.
- [x] 2025-11-06: Install EP kernel for CUDA released images.
- [x] 2025-11-07: Reinstall `lmcache` package for vLLM 0.11.0 CUDA released images.
- [x] 2025-11-10: Install `sglang[diffusion]` package for SGLang 0.5.5 CUDA released images.
- [x] 2025-11-12: Install `FlashAttention` package for SGLang 0.5.5 CUDA released images.
- [x] 2025-11-25: Install `Posix IPC` package for MindIE 2.2.rc1 CANN released images.
- [x] 2025-12-01: Apply Qwen2.5 VL patches to vLLM 0.11.2 for CUDA released images.
- [x] 2025-12-09: Install `AV` package for MindIE 2.2.rc1/2.1.rc2 CANN released images.
- [x] 2025-12-13: Apply MiniCPM Qwen2 V2 patches to MindIE 2.2.rc1/2.1.rc2 for CANN released images.
- [x] 2025-12-13: Apply server args patches to SGLang 0.5.6.post2 for CUDA released images.
- [x] 2025-12-14: Apply several patches to vLLM 0.12.0 and SGLang 0.5.6.post2 for CUDA released images.
- [x] 2025-12-15: Apply several patches to vLLM 0.11.0 and SGLang 0.5.6.post2 for CANN released images.
- [x] 2025-12-16: Uninstall `runai-model-streamer` packages from SGLang 0.5.6.post2 for CUDA released images.
- [x] 2025-12-19: Install `vLLM[audio]` packages for vLLM 0.12.0/0.11.2 of CUDA/ROCm released images.
- [x] 2025-12-19: Install `petit-kernel` package for vLLM 0.12.0/0.11.2 and SGLang 0.5.6.post2/0.5.5.post3 of ROcm released images.
- [x] 2025-12-24: Apply ATB config patches to MindIE 2.2.rc1 for CANN released images.
- [ ] 2026-01-05: Install `vllm-omni` packages for vLLM 0.12.0 of CUDA/ROCm/CANN released images.
- [x] 2026-01-29: Apply DP deployment patches to vLLM 0.13.0 for CUDA/ROCm released images.
- [x] 2026-01-29: Reinstall SGLang Kernel for SGLang 0.5.7 of CANN released images.
- [x] 2026-02-03: Apply several patches to vLLM 0.15.0/0.14.1 and SGLang 0.5.8 for CUDA 12.9 released images.
- [x] 2026-02-03: Patch SGLang 0.5.8/0.5.7 of CUDA/ROCm released images to disable CuDNN version check.
- [x] 2026-02-04: Reinstall `triton` package for vLLM 0.15.0/0.14.1 and SGLang 0.5.8 for ROCm released images.
- [x] 2026-02-04: Apply several patches to vLLM 0.15.0/0.14.1 and SGLang 0.5.8 for CUDA 12.8/12.6 released images.
- [x] 2026-02-05: Reinstall `nvidia-nccl-cu12` package to vLLM 0.15.0/0.14.1 and SGLang 0.5.8 for CUDA 12.9/12.8/12.6 released images.
- [x] 2026-02-12: Reinstall `triton` package for vLLM 0.15.1 for ROCm released images.
- [ ] 2026-02-14: Patch SGLang 0.5.8.post1 of CANN/CUDA/ROCm released images to reduce Z-Image loading memory occupation.
- [x] 2026-02-28: Reinstall `vllm-omni` packages for vLLM 0.16.0 of CUDA released images.
- [x] 2026-03-03: Fix malformed ARM64 image for vLLM 0.15.1 of CUDA released images.
- [x] 2026-09-01: Pin `numpy` to 1.26.4 and remove CUDA-only NIXL EP packages for vLLM 0.18.1 of DTK 26.04 released images.
- [x] 2026-09-16: Patch vLLM 0.24.0/0.25.1/0.27.1/0.29.0 of CUDA/ROCm released images to fix mooncake prom metrics issue.
