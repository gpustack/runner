# feat(pack): add Enflame GCU (燧原 S60) backend support

## Summary

Add Dockerfile support for Enflame GCU (燧原 S60) to the GPUStack runner pack system.

## Changes

- **New directory**: `pack/gcu/`
  - `Dockerfile` — Combined build with vanilla → runtime → vllm stages
  - `Dockerfile.vllm` — Per-service vLLM Dockerfile (runtime + vllm targets)
- **Modified**: `pack/matrix.yaml` — Added `gcu` backend rule

## Version Information

| Component | Version |
|-----------|---------|
| TopsRider (燧原加速框架) | 3.7.107 (i3x 3.6+) |
| vLLM-GCU | 0.11.0 |
| Python | 3.10 |
| OS | Ubuntu 22.04 |
| Hardware | S60 GCU |

## Vanilla Image

```
registry-egc.enflame-tech.com/artifacts/vllm_gcu:v0.11.0-TR3.7.107-ubuntu2204
```

This image is provided by Enflame and includes:
- Enflame GCU driver and TopsRider SDK
- `torch_gcu` (PyTorch for GCU)
- `vllm-gcu` (vLLM with GCU backend)
- `triton_gcu`

## Expected Image Tags

After the copy.yml workflow runs and the Dockerfiles are built:

| Stage | Tag |
|-------|-----|
| Vanilla | `gpustack/runner:gcu3.7.107-python3.10-vanilla` |
| Runtime | `gpustack/runner:gcu3.7.107-python3.10` |
| vLLM | `gpustack/runner:gcu3.7.107-vllm0.11.0-python3.10` |

## copy.yml Parameters

For the GitHub Action `copy.yml`, the suggested inputs:

```
src-registry: registry-egc.enflame-tech.com
src-image: artifacts/vllm_gcu:v0.11.0-TR3.7.107-ubuntu2204
dst-image-tag: gcu3.7.107-python3.10
```

## Build & Test

To build the runtime image locally:
```bash
docker build --progress=plain --platform=linux/amd64 \
  --file=pack/gcu/Dockerfile \
  --tag=gpustack/runner:gcu3.7.107-python3.10 \
  --target=runtime \
  pack/gcu
```

To build the vLLM image:
```bash
docker build --progress=plain --platform=linux/amd64 \
  --file=pack/gcu/Dockerfile \
  --tag=gpustack/runner:gcu3.7.107-vllm0.11.0-python3.10 \
  --target=vllm \
  pack/gcu
```

## Notes

- Only vLLM backend is supported (SGLang support not yet available for GCU)
- The vanilla image is Ubuntu 22.04 based
- Device visibility env var: `GCU_VISIBLE_DEVICES`
- Uses `RAY_EXPERIMENTAL_NOSET_GCU_VISIBLE_DEVICES=1` in entrypoint

## Related

- vLLM-GCU upstream: https://github.com/EnflameTechnology/vllm-gcu
- Enflame official: https://www.enflame-tech.com/
