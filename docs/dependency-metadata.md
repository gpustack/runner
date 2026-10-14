# Dependency metadata

Each entry of `gpustack_runner/runner.py.json` may carry a `dependencies` map recording versions
of a whitelisted set of Python packages as actually installed in the built image, not as declared
by Dockerfile `ARG`s. The whitelist lives in `pack/dependencies.json`, and collection runs on the
native platform for each image.

```json
{
  "docker_image": "gpustack/runner:cann9.1-a3-vllm0.23.0",
  "dependencies": {
    "lmcache": "0.4.3",
    "lmcache-ascend": "0.4.3",
    "torch": "2.10.0",
    "torch-npu": "2.10.0rc1",
    "vllm-ascend": "0.23.0"
  }
}
```

The build and collection path that produces this data is described in
[Packaging](packaging.md).

## Unknown versus empty dependencies

A missing key, an empty map and a present key mean three different things, and conflating them
leads to wrong conclusions.

| State | Meaning |
|-------|---------|
| `dependencies` is absent | Collection is unknown — the image predates probing, or collection was explicitly disabled |
| `dependencies` is `{}` | Collection succeeded and no configured dependency was present in the environment |
| `dependencies` is a map without the queried key | Collection succeeded, but the mapping recorded nothing for that name: the package is absent, or installed under a name the mapping does not cover |
| `dependencies` maps the queried key to a version | The package is installed, at that raw version |

An explicitly disabled collection is recorded with status `unknown` and carries no distributions,
so it yields the absent-field case rather than an empty map.

A genuinely empty Python environment does fail: enumerating zero installed distributions is
treated as a failure, because an empty environment is not evidence about selected packages. That
is distinct from a non-empty environment in which none of the configured packages appear — the
latter is a successful collection that folds to `{}`.

## Raw version preservation

The probe reports the versions as installed, without rounding, normalizing or truncating. Prerelease
markers survive unchanged — `2.10.0rc1` stays `2.10.0rc1` and is not rewritten to `2.10.0`.

Distribution names are normalized for comparison only (`-`, `_` and `.` runs collapse, case is
lowered), so a map key is stable; the recorded version is preserved verbatim.

Two distributions that normalize to the same *mapped* name with conflicting versions are an error
rather than a silent last-one-wins, because that state cannot be recorded truthfully. A conflict on
a name the mapping never records cannot corrupt the catalog, so it is ignored — vendor base images
routinely ship such duplicates.

The collector runs the probe inside the final platform image and writes its receipt outside the
image. Older post-operation Dockerfiles may still copy a
`/etc/gpustack-runner/dependencies.json` layer, but that historical metadata is not authoritative —
the receipt and the catalog entry are.

### One name, several distributions

A mapping key may list several candidate distributions in priority order. An alias is either a
literal distribution name or a prefix pattern: a name stem ending in `-` plus a single trailing
`*`. The `mooncake-transfer-engine` entry shows both forms:

```json
{
  "mooncake-transfer-engine": [
    "mooncake-transfer-engine-*",
    "mooncake-transfer-engine"
  ]
}
```

The pattern records the single installed distribution whose name starts with
`mooncake-transfer-engine-` — any current or future build variant, without a mapping edit. A stem
ends with `-`, so matching stays component-aligned: the pattern never matches the bare name
itself and cannot capture lookalikes such as `torchvision` under a `torch-*` stem. Pattern-first
order keeps the convention that a variant outranks the bare build when both are installed; the
bare literal is the generic fallback. Folding happens only after the complete artifact set is
validated. Zero pattern matches pass to the next candidate; two or more installed distributions
under one stem fail the fold as ambiguous, because recording either would be arbitrary.

Two conditions must both hold before grouping — a pattern changes syntax, not policy:

1. Mutually exclusive — at most one can be installed in a given image. Folding keeps a single
   winner, so grouping distributions that coexist silently discards one of them. `torch` and
   `torch-npu` look like such a pair but are not: `torch-npu` pins `torch` and sits on top of it,
   so both are installed with meaningful versions. The same holds for `lmcache` and
   `lmcache-ascend`.
2. Comparable versions — same versioning scheme, ideally the same release line. `sglang-kernel`
   and `sgl-kernel-npu` are mutually exclusive but stay separate, because a specifier meaningful
   for a `0.4.6.post1` version is meaningless against a `2026.6.1` date version.

A stem wildcard additionally asserts that everything under the prefix is a build variant of one
package — true for `mooncake-transfer-engine`, false for the `vllm`, `sglang` or `lmcache`
prefixes, which mix distinct packages. Validation rejects a pattern whose stem would claim a
distribution another key records, so a hypothetical `vllm-*` pattern fails against the
`vllm-ascend` and similar keys. When in doubt, give each distribution its own name. That records
both facts and asserts nothing.

## Querying

`list_runners`, `list_backend_runners` and `list_service_runners` accept a `dependencies`
argument: a tuple of `(dependency name, PEP 440 specifier)` pairs, matched against the
`dependencies` map of each entry.

```python
# Images whose lmcache is new enough.
list_runners(service="vllm", dependencies=(("lmcache", ">=0.4.6"),))

# Multiple conditions.
list_runners(backend="cuda", dependencies=(("lmcache", ">=0.4.6"), ("torch", ">=2.9"),))

# An empty specifier asks only whether the name was recorded.
list_runners(backend="cuda", dependencies=(("vllm-omni", ""),))

# Strict mode: drop images that were never probed.
list_runners(
    backend="cuda",
    dependencies=(("lmcache", ">=0.4.6"),),
    with_unknown_dependencies=False,
)
```

1. Conditions are ANDed. A runner must satisfy every pair; there is no "any of" form.
2. Unprobed runners are kept by default. A runner whose `dependencies` field is absent is not
   filtered out, so adding a condition does not make every pre-existing image disappear at once.
   `with_unknown_dependencies=False` keeps only runners known to satisfy the condition, so expect
   a much shorter list until the fleet is rebuilt. A runner with an empty map is not unprobed: it
   fails any condition, because no key can satisfy it.
3. Prereleases match. Matching uses `prereleases=True`, because rc versions are routine here. The
   converse is not a bug: `>=0.4.6` does not match `0.4.6rc1`, since PEP 440 orders
   `0.4.6rc1 < 0.4.6`. The same applies to dev versions such as `0.27.0rc2.dev25+g<sha>`. Write
   the bound you actually mean (`>=0.4.6rc1`).
4. An empty specifier checks only whether the mapping recorded the name. It also works when the
   recorded version cannot be parsed as a PEP 440 version.
5. An unknown name matches no collected row and does not raise. The whitelist is a build-side file
   and is not shipped with the library, so there is nothing to validate a name against. A
   misspelled name yields the same result as "no image qualifies"; callers own their spelling.
   Remember that unprobed rows remain in the result unless `with_unknown_dependencies=False` is
   passed.

Query names must match keys in the `dependencies` map. Versions are stored verbatim, then parsed
as PEP 440 versions for nonempty specifiers. A mapping entry does not guarantee installation in
every image.

## Accelerator suffixes in vLLM versions

Accelerator builds of vLLM are published as one distribution whose `VERSION` carries a local
suffix, such as `0.29.0+cu129` or `0.29.0+rocm723`. These are suffixes of the version, not of the
distribution name. Accelerator plugins are separate distributions in their own right, such as
`vllm-ascend`, recorded under their own name. Dependency queries accept version ranges for
plugins too; exact plugin matching applies to support promotion.

Support promotion compares the collected installed version against the version the matrix
requested. An exact match passes. Otherwise, for vLLM only, the comparison also accepts a build
whose local suffix is the accelerator identifier for that backend (`cu<digits>` for cuda,
`rocm<digits>` for rocm) when the requested version carries no suffix of its own and the public
parts are equal. The comparison is limited to release identity:

- Raw measured versions are retained in the resulting metadata; the suffix is not stripped.
- The plugin is compared exactly, not by suffix rule.
- This invocation's measured results cover every platform declared by the support row.
- Runtime and backend variant match; older catalog results cannot supply missing platform evidence.
- Development-tag rows never promote.

These records describe configuration and measured package coverage for the intended platforms.
They do not verify runtime compatibility; GPU verification is a separate concern, and the row
status alone never asserts it. See [Support records](support-records.md).

## Extending the whitelist

The bar for adding a package to `pack/dependencies.json` is: it directly decides whether a model
or the inference backend starts, and it is updated often or breaks compatibility. Keep the list
short. Before grouping accelerator-specific variants under one name, confirm they are mutually
exclusive as described above.

Related: [Packaging](packaging.md) covers receipt collection and promotion;
[Support records](support-records.md) covers support records and status semantics.
