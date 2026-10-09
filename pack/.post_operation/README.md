# Post Profile of GPUStack Runner

Normally, images are immutable.
However, for some needs, we have to modify the image's content while preserving its tag.

> [!CAUTION]
> - This behavior is **DANGEROUS** and **NOT RECOMMENDED**.
> - This behavior is **NOT IDEMPOTENT** and therefore **CANNOT BE REVERSED** after released.

We leverage the matrix expansion feature of GPUStack Runner to achieve this, and document here the operations we perform.

## Requirements for a New Operation

`gpustack_runner/runner.py.json` records installed dependency versions for each image
and CPU platform. An operation can change those versions behind an existing tag.
Pack therefore collects metadata from the final single-platform image digest after
the operation finishes. Central collection is authoritative for catalog updates.

New operations need only the runtime service target:

```dockerfile
FROM gpustack/runner:<released-tag> AS vllm

# ... the operation itself ...

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
```

Replace `vllm` with the operation's service target. New recipes require no probe
arguments, helper mounts, embedded metadata, or dependency export stages.
Explicit post operations may retain unsuffixed `Dockerfile` names.

Existing historical recipes remain unchanged. Pack supplies the named context
`shared` only when a post operation is explicitly selected. This preserves recipes
that still mount `pack/shared/probe_dependencies.sh`. Their embedded output does
not supply catalog metadata, and Pack does not build their export stages.

Running such an operation:

- Run it with `for_release=true`. Otherwise every tag carries the `-dev` suffix and
  addresses no released entry.
- Pack validates the complete set of collection receipts against the final image
  digests and platforms. A missing or failed collection blocks the catalog update.
  It does not reuse old dependency versions for the replacement image.
- `merge_runner.sh` updates only `dependencies` on exactly one matching existing
  row per platform image. It does not add a row or change other fields.
  Zero or multiple matches fail the job.
- The run opens the usual `chore: update runner` pull request, which also regenerates
  `tests/gpustack_runner/fixtures/`. A fixture diff unrelated to the operation is
  therefore possible and not, by itself, a sign that something went wrong.

The records below describe past operations. This change does not rerun them or
refresh their existing catalog rows. If selected again, they use central collection.

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
- [ ] 2026-09-20: Install `vllm-router` package for vLLM 0.27.1 of CUDA released images.
- [ ] 2026-09-24: Patch vLLM 0.29.0 of CUDA/ROCm released images to fix mooncake store pending load assertion.
