# Post Profile of GPUStack Runner

Normally, images are immutable.
However, for some needs, we have to modify the image's content while preserving its tag.

**This behavior is dangerous and not recommended.**

We leverage the matrix expansion feature of GPUStack Runner to achieve this, and document here the operations we perform.

- [x] 2025-10-20: Install `lmcache` package for CANN/CUDA/ROCm released images.
