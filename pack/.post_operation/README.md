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
- [x] 2025-11-10: Install diffusion extension package for SGLang 0.5.5 CUDA released images.
- [x] 2025-11-12: Install FlashAttention package for SGLang 0.5.5 CUDA released images.
- [x] 2025-11-25: Install Posix IPC package for MindIE 2.2.rc1 CANN released images.
- [x] 2025-12-01: Apply Qwen2.5 VL patches to vLLM 0.11.2 for CUDA released images.
- [x] 2025-12-09: Install AV package for MindIE 2.2.rc1 and 2.1.rc2 CANN released images.
- [x] 2025-12-13: Apply MiniCPM Qwen2 V2 patches to MindIE 2.2.rc1 and 2.1.rc2 for CANN released images.
- [x] 2025-12-13: Apply server args patches to SGLang 0.5.6.post2 for CUDA released images.
- [x] 2025-12-14: Apply several patches to vLLM 0.12.0 and SGLang 0.5.6.post2 for CUDA released images.
- [x] 2025-12-15: Apply several patches to vLLM 0.11.0 and SGLang 0.5.6.post2 for CANN released images.
- [ ] 2025-12-16: Uninstall `runai-model-streamer` packages from SGLang 0.5.6.post2 for CUDA released images.
