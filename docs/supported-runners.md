# Supported runners

## Support records

A `prepared` row records a merged configuration proposal. It does not claim an image exists.
A `published` row records complete platform coverage verified by Pack.
Pack checks build outputs, measured dependencies, and registry manifests before changing this status.
Its measured `vllm` or `sglang` version must match the declared engine version on every listed platform.
For CANN vLLM, the measured `vllm-ascend` version must also match the declared plugin version.
Missing collection results, different versions, and partial platform coverage leave the record `prepared`.
Catalog maintenance does not change support status.

Add new support as one row per backend, runtime line, service, accelerator variant, and engine/plugin pair.
List the intended Linux CPU platforms explicitly. Use `-` for an absent variant or plugin.
CANN vLLM rows require the actual `vllm-ascend` version, including its prerelease suffix.
Other rows use `-` for Plugin. Runtime is the catalog runtime line, such as `9.1`, rather than its patch version.
Rows with the same identity and platform set must be unique.

<!-- runner-support-records:start -->
| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
<!-- runner-support-records:end -->

## Historical support tables

The tables below retain the original support information and annotations.
They do not specify CPU platforms or exact accelerator plugin versions.
In particular, an engine followed by `(rc)` has an unknown plugin identity.
It cannot establish support for a specific Ascend prerelease plugin.
The generated catalog can provide the measured plugin version when its dependency metadata is present.


> [!TIP]
> - The list below shows the accelerated backends and inference services available in the latest release. For support of
    backends or services not shown here, please refer to previous release tags.
> - Deprecated inference service versions in the latest release are marked with ~~strikethrough~~ formatting. They may
    still be available in previous releases, and not recommended for new deployments.
> - Polished inference service versions in the latest release are marked with **bold** formatting. If they are using in
    your deployment, it is recommended to pull the latest images and upgrade.

The following table lists the supported accelerated backends and their corresponding inference services with versions.

### Ascend CANN

| CANN Version <br/> (Variant) | MindIE    | vLLM                                                                                 | SGLang                                      |
|------------------------------|-----------|--------------------------------------------------------------------------------------|---------------------------------------------|
| 9.1 (950/A5)                 |           | **`0.23.0`**                                                                         |                                             |
| 9.1 (A3/910C)                |           | **`0.23.0`**                                                                         |                                             |
| 9.1 (910B)                   |           | **`0.23.0`**                                                                         |                                             |
| 9.1 (310P)                   |           | **`0.23.0`**                                                                         |                                             |
| 9.0 (A3/910C)                |           | `0.20.2`(rc)                                                                         | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`     |
| 9.0 (910B)                   |           | `0.20.2`(rc)                                                                         | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`     |
| 9.0 (310P)                   |           | `0.20.2`(rc)                                                                         |                                             |
| 8.5 (A3/910C)                | `2.3.0`   | `0.18.0`, `0.17.0`(rc), <br/>`0.16.0`(rc), `0.15.0`(rc), <br/>`0.14.1`(rc), `0.13.0` | `0.5.12.post1`, <br/>`0.5.9`, `0.5.8.post1` |
| 8.5 (910B)                   | `2.3.0`   | `0.18.0`, `0.17.0`(rc), <br/>`0.16.0`(rc), `0.15.0`(rc), <br/>`0.14.1`(rc), `0.13.0` | `0.5.12.post1`, <br/>`0.5.9`, `0.5.8.post1` |
| 8.5 (310P)                   | `2.3.0`   | `0.18.0`, `0.17.0`(rc), <br/>`0.16.0`(rc), `0.15.0`(rc), <br/>`0.14.1`(rc)           |                                             |
| 8.3 (A3/910C)                | `2.2.rc1` | `0.12.0`(rc), `0.11.0`                                                               | `0.5.7`, `0.5.6.post2`                      |
| 8.3 (910B)                   | `2.2.rc1` | `0.12.0`(rc), `0.11.0`                                                               | `0.5.7`, `0.5.6.post2`                      |
| 8.3 (310P)                   | `2.2.rc1` |                                                                                      |                                             |
| 8.2 (A3/910C)                | `2.1.rc2` | `0.10.2`(rc)                                                                         |                                             |
| 8.2 (910B)                   | `2.1.rc2` | `0.10.2`(rc), `0.10.0`(rc),  <br/>`0.9.1`                                            |                                             |
| 8.2 (310P)                   | `2.1.rc2` | `0.10.0`(rc), `0.9.1`                                                                |                                             |

### Iluvatar CoreX

| CoreX Version <br/> (Variant) | vLLM    |
|-------------------------------|---------|
| 4.2                           | `0.8.3` |

### NVIDIA CUDA

| CUDA Version <br/> (Variant) | vLLM                                                                                                                                                                                                              | SGLang                                                                                                            | VoxBox   |
|------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|----------|
| 13.0                         | **`0.29.0`**, **`0.27.1`**,<br/> **`0.25.1`**, **`0.24.0`**,<br/> `0.22.1`, `0.21.0`,<br/> `0.20.2`, `0.19.1`,<br/> `0.18.1`                                                                                      | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`, `0.5.12.post1`                                                           |          |
| 12.9                         | **`0.29.0`**, **`0.27.1`**,<br/> **`0.25.1`**, **`0.24.0`**,<br/> `0.22.1`, `0.21.0`,<br/> `0.20.2`, `0.19.1`,<br/> `0.18.1`, `0.17.1`,<br/> `0.16.0`, `0.15.1`,<br/> `0.14.1`, `0.13.0`,<br/> `0.12.0`, `0.11.2` | `0.5.18`, `0.5.15.post1`,<br/> `0.5.14`, `0.5.12.post1`, <br/>`0.5.9`, `0.5.8.post1`, <br/>`0.5.7`, `0.5.6.post2` |          |
| 12.8                         | `0.17.1`, `0.16.0`, <br/>`0.15.1`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2`                                                                                                                     | `0.5.9`, `0.5.8.post1`, <br/>`0.5.7`, `0.5.6.post2`, <br/>`0.5.5.post3`                                           | `0.0.21` |
| 12.6                         | `0.15.1`, `0.14.1`, <br/>`0.13.0`, `0.12.0`, <br/>`0.11.2`, `0.10.2`                                                                                                                                              |                                                                                                                   | `0.0.21` |

### Hygon DTK

| DTK Version <br/> (Variant) | vLLM                                      | SGLang       |
|-----------------------------|-------------------------------------------|--------------|
| 26.04                       | **`0.18.1`**                              | `0.5.10`(rc) |
| 25.04                       | `0.18.1`, `0.11.0`,<br/> `0.9.2`, `0.8.5` |              |

### T-Head HGGC

| HGGC Version <br/> (Variant) | vLLM                                        | SGLang                           |
|------------------------------|---------------------------------------------|----------------------------------|
| 13.0                         | `0.23.0`, `0.20.1`,<br/> `0.19.0`, `0.18.0` | `0.5.12`, `0.5.10`,<br/> `0.5.9` |
| 12.3                         | `0.12.0`, `0.11.1`                          | `0.5.6`, `0.5.5`                 |

### MetaX MACA

| MACA Version <br/> (Variant) | vLLM               | SGLang             |
|------------------------------|--------------------|--------------------|
| 3.7                          | `0.21.0`, `0.20.0` | `0.5.11`, `0.5.10` |
| 3.5                          | `0.14.0`           | `0.5.9`            |
| 3.3                          | `0.11.2`           | `0.5.6`            |
| 3.2                          | `0.10.2`           |                    |
| 3.0                          | `0.9.1`            |                    |

### MThreads MUSA

| MUSA Version <br/> (Variant) | vLLM    | SGLang  |
|------------------------------|---------|---------|
| 4.3.2                        |         | `0.5.7` |
| 4.1.0                        | `0.9.2` |         |

### AMD ROCm

| ROCm Version <br/> (Variant) | vLLM                                                                                                          | SGLang                                                    |
|------------------------------|---------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------|
| 7.2                          | **`0.29.0`**, **`0.27.1`**,<br/> **`0.25.1`**, **`0.24.0`**,<br/> `0.22.1`, `0.21.0`,<br/> `0.20.2`, `0.19.1` | `0.5.18`, `0.5.15.post1`, <br/>`0.5.14`, `0.5.12.post1`   |
| 7.1                          | `0.17.1`                                                                                                      |                                                           |
| 7.0                          | `0.18.1`, `0.16.0`,<br/> `0.15.1`, `0.14.1`,<br/> `0.13.0`, `0.12.0`,<br/> `0.11.2`                           | `0.5.9`, `0.5.8.post1`, <br/>`0.5.7`, `0.5.6.post2`       |
| 6.4                          | `0.16.0`, `0.15.1`,<br/> `0.14.1`, `0.13.0`,<br/> `0.12.0`, `0.11.2`,<br/> `0.10.2`                           | `0.5.8.post1`, `0.5.7`, <br/>`0.5.6.post2`, `0.5.5.post3` |
