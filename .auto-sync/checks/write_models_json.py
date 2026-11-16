"""Generate Pi models.json and GitHub Action outputs for auto-sync."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PI_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
NON_OFF_THINKING_LEVELS = PI_THINKING_LEVELS - {"off"}
PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DISALLOWED_OAUTH_PROVIDERS = {
    "github-copilot",
    "openai-codex",
    "claude-code",
    "gemini",
    "google",
    "gemini-cli",
    "google-gemini-cli",
    "google-antigravity",
}
DEFAULT_MAX_TOKENS = 32768
DEFAULT_CONTEXT_WINDOW = 128000
DEFAULT_TASKPACK_PROVIDER = "zai-coding-cn"
DEFAULT_TASKPACK_MODEL = "glm-5.3"
GLM5_CONTEXT_WINDOW = 1_000_000
MIN_SAMPLING_PARAM = -4.0
MAX_SAMPLING_PARAM = 4.0


def _default_context_window(model: str) -> int:
    lowered = model.strip().lower()
    if lowered.startswith("glm-5") or "/glm-5" in lowered:
        return GLM5_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW


def _validate_base_url(raw: str) -> str:
    if (
        len(raw) < 8
        or len(raw) > 2048
        or any(ch.isspace() or ord(ch) < 32 for ch in raw)
    ):
        msg = "LLM base URL must be a valid single-line URL without whitespace"
        raise ValueError(msg)
    if "?" in raw or "#" in raw:
        msg = "LLM base URL must not contain query or fragment"
        raise ValueError(msg)
    parsed = urlsplit(raw)
    if parsed.username or parsed.password:
        msg = "LLM base URL must not contain credentials"
        raise ValueError(msg)
    loopback = (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port is not None
    )
    if not ((parsed.scheme == "https" and bool(parsed.hostname)) or loopback):
        msg = "LLM base URL must be https://<host>... or http://127.0.0.1:<port>..."
        raise ValueError(msg)
    return raw


def _resolve_api(protocol: str, use_anthropic: str) -> str:
    proto = protocol.strip().lower()
    if proto:
        mapping = {
            "openai": "openai-completions",
            "openai-completions": "openai-completions",
            "openai-responses": "openai-responses",
            "anthropic": "anthropic-messages",
            "anthropic-messages": "anthropic-messages",
        }
        if proto not in mapping:
            msg = f"unsupported LLM protocol: {protocol!r}"
            raise ValueError(msg)
        return mapping[proto]
    flag = use_anthropic.strip().lower()
    if flag in {"true", "1", "yes"}:
        return "anthropic-messages"
    if flag in {"false", "0", "no", ""}:
        return "openai-completions"
    msg = f"invalid use-anthropic boolean string: {use_anthropic!r}"
    raise ValueError(msg)


def _snap_thinking_level(
    model: str,
    level: str,
    *,
    thinking_enabled: bool,
    provider: str = "",
) -> tuple[str, bool]:
    norm_model = model.strip().lower().rsplit("/", 1)[-1]
    norm_provider = provider.strip().lower()
    uses_zai_builtin_map = norm_provider in {"", "zai", "zai-coding-cn"}

    if norm_model.startswith("glm-5.3") and uses_zai_builtin_map:
        # Built-in zai/glm-5.3 only maps low/high/max, and taskpack.yaml pins
        # zai-coding-cn/glm-5.3 as a reasoning-capable model.
        if not thinking_enabled or level in {"off", "minimal", "low"}:
            return "low", True
        if level in {"medium", "high", "xhigh"}:
            return "high", True
        return "max", True

    if norm_model.startswith("glm-5.2") and uses_zai_builtin_map:
        if not thinking_enabled or level == "off":
            return "off", False
        if level == "max":
            return "max", True
        return "high", True

    if not thinking_enabled or level == "off":
        return "off", False
    if level == "max":
        return "xhigh", True
    return level, True


def _resolve_thinking(
    thinking: str,
    reasoning_effort: str,
    *,
    model: str = "",
    base_url: str = "",
    provider: str = "",
) -> tuple[str, bool]:
    think_norm = thinking.strip().lower()
    effort_norm = reasoning_effort.strip().lower()

    if think_norm in {"disabled", "off"}:
        if effort_norm and effort_norm not in NON_OFF_THINKING_LEVELS:
            msg = f"unsupported reasoning_effort: {reasoning_effort!r}"
            raise ValueError(msg)
        return _snap_thinking_level(
            model,
            "off",
            thinking_enabled=False,
            provider=provider,
        )

    if effort_norm:
        if effort_norm not in NON_OFF_THINKING_LEVELS:
            msg = f"unsupported reasoning_effort: {reasoning_effort!r}"
            raise ValueError(msg)
        if think_norm and think_norm not in {"enabled", *NON_OFF_THINKING_LEVELS}:
            msg = f"unsupported thinking value: {thinking!r}"
            raise ValueError(msg)
        return _snap_thinking_level(
            model,
            effort_norm,
            thinking_enabled=True,
            provider=provider,
        )

    if think_norm:
        if think_norm == "enabled":
            return _snap_thinking_level(
                model,
                "low",
                thinking_enabled=True,
                provider=provider,
            )
        if think_norm in NON_OFF_THINKING_LEVELS:
            return _snap_thinking_level(
                model,
                think_norm,
                thinking_enabled=True,
                provider=provider,
            )
        msg = f"unsupported thinking value: {thinking!r}"
        raise ValueError(msg)

    hint = f"{model} {base_url}".lower()
    if "glm" in hint or "zai" in hint or "bigmodel.cn" in hint:
        return _snap_thinking_level(
            model,
            "low",
            thinking_enabled=True,
            provider=provider,
        )
    return _snap_thinking_level(
        model,
        "off",
        thinking_enabled=False,
        provider=provider,
    )


def _parse_sampling_float(raw: str, name: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        msg = f"{name} must be a finite number"
        raise ValueError(msg) from exc
    if (
        not math.isfinite(value)
        or not MIN_SAMPLING_PARAM <= value <= MAX_SAMPLING_PARAM
    ):
        msg = f"{name} must be within [-4, 4]"
        raise ValueError(msg)
    if value == 0.0:
        value = 0.0
    return value


def _parse_int_range(
    raw: str,
    name: str,
    minimum: int,
    maximum: int,
    default: int,
) -> int:
    text = raw.strip()
    if not text:
        return default
    if not text.isdigit():
        msg = f"{name} must be an integer"
        raise ValueError(msg)
    value = int(text)
    if not minimum <= value <= maximum:
        msg = f"{name} must be in [{minimum}, {maximum}]"
        raise ValueError(msg)
    return value


def _resolve_provider(provider: str, base_url: str) -> str:
    explicit = provider.strip()
    if explicit:
        if (
            not PROVIDER_ID_RE.match(explicit)
            or ".." in explicit
            or explicit in DISALLOWED_OAUTH_PROVIDERS
        ):
            msg = f"unsupported LLM provider identifier: {provider!r}"
            raise ValueError(msg)
        return explicit

    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host == "open.bigmodel.cn" or host.endswith(".bigmodel.cn"):
        return "zai-coding-cn" if "/api/coding" in path else "zai-cn"
    if host == "api.z.ai" or host.endswith(".z.ai"):
        return "zai"
    host_map = {
        "api.anthropic.com": "anthropic",
        "api.openai.com": "openai",
        "api.deepseek.com": "deepseek",
        "openrouter.ai": "openrouter",
        "api.moonshot.cn": "moonshotai-cn",
        "api.moonshot.ai": "moonshotai",
        "api.kimi.com": "kimi-coding",
        "api.minimaxi.com": "minimax-cn",
        "api.minimax.io": "minimax",
        "token-plan.cn-beijing.maas.aliyuncs.com": "qwen-token-plan-cn",
        "dashscope.aliyuncs.com": "qwen-token-plan-cn",
        "token-plan.ap-southeast-1.maas.aliyuncs.com": "qwen-token-plan",
        "dashscope-intl.aliyuncs.com": "qwen-token-plan",
        "api.fireworks.ai": "fireworks",
        "api.together.xyz": "together",
        "inference.baseten.co": "baseten",
        "integrate.api.nvidia.com": "nvidia",
        "api.groq.com": "groq",
        "api.cerebras.ai": "cerebras",
        "api.mistral.ai": "mistral",
        "api.x.ai": "xai",
        "router.huggingface.co": "huggingface",
        "ai-gateway.vercel.sh": "vercel-ai-gateway",
        "token-plan-cn.xiaomimimo.com": "xiaomi-token-plan-cn",
        "token-plan-sgp.xiaomimimo.com": "xiaomi-token-plan-sgp",
        "token-plan-ams.xiaomimimo.com": "xiaomi-token-plan-ams",
        "api.xiaomimimo.com": "xiaomi",
        "api.ant-ling.com": "ant-ling",
    }
    return host_map.get(host, "custom-gateway")


def _write_github_output(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}\n" for key, value in values.items()]
    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)


def build_models_config(
    *,
    url: str,
    model: str,
    provider: str = "",
    protocol: str = "",
    use_anthropic: str = "",
    thinking: str = "",
    reasoning_effort: str = "",
    temperature: str = "",
    top_p: str = "",
    max_tokens: str = "",
    context_window: str = "",
) -> tuple[dict[str, object] | None, dict[str, str]]:
    clean_url = url.strip()
    clean_model = model.strip()
    if not clean_url and not clean_model:
        provider_out = ""
        if provider.strip():
            provider_out = _resolve_provider(provider, "")
        thinking_out = ""
        if thinking.strip() or reasoning_effort.strip():
            default_model = (
                DEFAULT_TASKPACK_MODEL
                if provider_out in {"", "zai", DEFAULT_TASKPACK_PROVIDER}
                else ""
            )
            thinking_out, _ = _resolve_thinking(
                thinking,
                reasoning_effort,
                model=default_model,
                provider=provider_out or DEFAULT_TASKPACK_PROVIDER,
            )
        return None, {
            "provider": provider_out,
            "model": "",
            "thinking": thinking_out,
            "api": "",
            "base-url": "",
            "models-json": "",
        }

    if not clean_url or not clean_model:
        msg = "both CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL and CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL must be set together"
        raise ValueError(msg)
    if any(ch.isspace() for ch in clean_model) or len(clean_model) > 128:
        msg = "LLM model identifier must be 1..128 non-whitespace characters"
        raise ValueError(msg)

    base_url = _validate_base_url(clean_url)
    provider_id = _resolve_provider(provider, base_url)
    api = _resolve_api(protocol, use_anthropic)
    thinking_level, reasoning = _resolve_thinking(
        thinking,
        reasoning_effort,
        model=clean_model,
        base_url=base_url,
        provider=provider_id,
    )
    max_tokens_val = _parse_int_range(
        max_tokens,
        "max_tokens",
        1,
        1_048_576,
        DEFAULT_MAX_TOKENS,
    )
    context_window_val = _parse_int_range(
        context_window,
        "context_window",
        1024,
        10_000_000,
        _default_context_window(clean_model),
    )

    sampling: dict[str, float] = {}
    temp_val = _parse_sampling_float(temperature, "temperature")
    if temp_val is not None:
        sampling["temperature"] = temp_val
    top_p_val = _parse_sampling_float(top_p, "top_p")
    if top_p_val is not None:
        sampling["top_p"] = top_p_val

    model_entry: dict[str, object] = {
        "id": clean_model,
        "api": api,
        "baseUrl": base_url,
        "reasoning": reasoning,
        "contextWindow": context_window_val,
        "maxTokens": max_tokens_val,
    }
    if sampling:
        model_entry["samplingParams"] = sampling
    lowered_model = clean_model.lower()
    lowered_url = base_url.lower()
    if api == "openai-completions" and (
        "glm" in lowered_model or "zai" in lowered_url or "bigmodel.cn" in lowered_url
    ):
        compat: dict[str, object] = {"thinkingFormat": "zai"}
        if not (lowered_model.startswith("glm-4") or "/glm-4" in lowered_model):
            compat["supportsReasoningEffort"] = True
        model_entry["compat"] = compat

    payload: dict[str, object] = {
        "providers": {
            provider_id: {
                "baseUrl": base_url,
                "api": api,
                "apiKey": "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN",
                "models": [model_entry],
            },
        },
    }
    outputs = {
        "provider": provider_id,
        "model": clean_model,
        "thinking": thinking_level,
        "api": api,
        "base-url": base_url,
    }
    return payload, outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output models.json path.",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="Optional GitHub Actions output file.",
    )
    args = parser.parse_args(argv)

    try:
        payload, outputs = build_models_config(
            url=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL", ""),
            model=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL", ""),
            provider=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROVIDER", ""),
            protocol=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL", ""),
            use_anthropic=os.environ.get(
                "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_USE_ANTHROPIC",
                "",
            ),
            thinking=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_THINKING", ""),
            reasoning_effort=os.environ.get(
                "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_REASONING_EFFORT",
                "",
            ),
            temperature=os.environ.get(
                "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TEMPERATURE",
                "",
            ),
            top_p=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TOP_P", ""),
            max_tokens=os.environ.get("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MAX_TOKENS", ""),
            context_window=os.environ.get(
                "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_CONTEXT_WINDOW_SIZE",
                "",
            ),
        )
        if payload is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
            outputs["models-json"] = str(args.output)
        _write_github_output(args.github_output, outputs)
    except (ValueError, OSError) as exc:
        print(f"models.json generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
