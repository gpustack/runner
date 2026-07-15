# Enflame GCU (燧原 S60) Backend Support Request

## Version Information

| Component | Version | Notes |
|-----------|---------|-------|
| **vLLM-GCU** | 0.11.0 | Fork of vLLM 0.11.0 with GCU support |
| **TopsRider (燧原加速框架)** | 3.7.107 | i3x 3.6+ series |
| **Ubuntu** | 22.04 | LTS |
| **Python** | 3.10 | (3.10 ~ 3.12 supported) |
| **Hardware** | S60 GCU | Enflame GCU accelerator |
| **PyTorch** | torch_gcu | Provided in vanilla image |

## Vanilla Image

```
registry-egc.enflame-tech.com/artifacts/vllm_gcu:v0.11.0-TR3.7.107-ubuntu2204
```

This image already includes:
- Enflame GCU driver and TopsRider SDK
- torch_gcu (PyTorch for GCU)
- vllm-gcu (vLLM with GCU backend)
- triton_gcu

## Supported Models

vLLM-GCU supports a wide range of models including:
- Qwen series (Qwen1.5/2/2.5/3, Qwen3-MoE, Qwen3-Next)
- LLaMA series (LLaMA 2/3/3.1)
- DeepSeek series (V3/R1/V3.2, Prover V2)
- ChatGLM series (GLM3, GLM4)
- Baichuan, Gemma, Mistral, Yi, InternLM, Mixtral, etc.
- VLM models: Qwen2.5-VL, Step3-VL, GOT-OCR2, PaddleOCR-VL

## Quantization Support

- GPTQ (4-bit/8-bit)
- AWQ (4-bit/8-bit)
- W8A16
- INT8 KV Cache

## GitHub Repository

https://github.com/EnflameTechnology/vllm-gcu

## Dockerfile Location

Dockerfiles have been added to `pack/gcu/`:
- `pack/gcu/Dockerfile` - Combined runtime + vLLM stages
- `pack/gcu/Dockerfile.vllm` - Per-service vLLM Dockerfile

## copy.yml Workflow Parameters

For the copy.yml workflow, the suggested parameters are:

```
src-registry: registry-egc.enflame-tech.com
src-image: artifacts/vllm_gcu:v0.11.0-TR3.7.107-ubuntu2204
src-username: [Enflame registry username]
src-token: [Enflame registry token]
dst-image-tag: gcu3.7.107-python3.10
```

This will produce the vanilla image:
```
gpustack/runner:gcu3.7.107-python3.10-vanilla
```

## Build Output Tags

Following the naming convention of other backends:

| Stage | Expected Tag |
|-------|-------------|
| Vanilla | `gpustack/runner:gcu3.7.107-python3.10-vanilla` |
| Runtime | `gpustack/runner:gcu3.7.107-python3.10` |
| vLLM | `gpustack/runner:gcu3.7.107-vllm0.11.0-python3.10` |

## Notes

1. SGLang support is not yet available for GCU. Only vLLM backend is supported.
2. The vanilla image is based on Ubuntu 22.04.
3. The TopsRider SDK path is typically `/usr/local/gcu` or similar.
4. Environment variable for device visibility: `GCU_VISIBLE_DEVICES` (ray: `RAY_EXPERIMENTAL_NOSET_GCU_VISIBLE_DEVICES=1`).
