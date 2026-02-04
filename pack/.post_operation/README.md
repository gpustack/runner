# Post Profile of GPUStack Runner

Normally, images are immutable.
However, for some needs, we have to modify the image's content while preserving its tag.

> [!CAUTION]
> - This behavior is **DANGEROUS** and **NOT RECOMMENDED**.
> - This behavior is **NOT IDEMPOTENT** and therefore **CANNOT BE REVERSED** after released.

We leverage the matrix expansion feature of GPUStack Runner to achieve this, and document here the operations we perform.

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
- [x] 2026-02-03: Apply several patches to vLLM 0.14.1/0.15.0 and SGLang 0.5.8 for CUDA 12.9 released images.
- [x] 2026-02-03: Patch SGLang 0.5.8/0.5.7 of CUDA/ROCm released images to disable CuDNN version check.
- [ ] 2026-02-04: Reinstall `triton` package for vLLM 0.15.0/0.14.1 and SGLang 0.5.8 for ROCm released images.
