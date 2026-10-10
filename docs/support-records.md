# Support records

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
| cuda | 12.9 | vllm | - | 0.30.0 | - | linux/amd64, linux/arm64 | prepared |
| cuda | 13.0 | vllm | - | 0.30.0 | - | linux/amd64, linux/arm64 | prepared |
| cuda | 13.0 | sglang | - | 0.5.21 | - | linux/amd64, linux/arm64 | prepared |
| rocm | 7.2 | vllm | - | 0.30.0 | - | linux/amd64 | prepared |
| rocm | 7.2 | sglang | - | 0.5.21 | - | linux/amd64 | prepared |
<!-- runner-support-records:end -->
