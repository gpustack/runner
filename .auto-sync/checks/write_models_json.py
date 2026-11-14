"""Generate Pi models.json and GitHub Action outputs for auto-sync."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

PI_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
NON_OFF_THINKING_LEVELS = PI_THINKING_LEVELS - {"off"}
DEFAULT_MAX_TOKENS = 32768
DEFAULT_CONTEXT_WINDOW = 128000
MIN_SAMPLING_PARAM = -4.0
MAX_SAMPLING_PARAM = 4.0


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


def _resolve_thinking(
    thinking: str,
    reasoning_effort: str,
    *,
    model: str = "",
    base_url: str = "",
) -> tuple[str, bool]:
    think_norm = thinking.strip().lower()
    effort_norm = reasoning_effort.strip().lower()

    if think_norm in {"disabled", "off"}:
        if effort_norm and effort_norm not in NON_OFF_THINKING_LEVELS:
            msg = f"unsupported reasoning_effort: {reasoning_effort!r}"
            raise ValueError(msg)
        return "off", False

    if effort_norm:
        if effort_norm not in NON_OFF_THINKING_LEVELS:
            msg = f"unsupported reasoning_effort: {reasoning_effort!r}"
            raise ValueError(msg)
        if think_norm and think_norm not in {"enabled", *NON_OFF_THINKING_LEVELS}:
            msg = f"unsupported thinking value: {thinking!r}"
            raise ValueError(msg)
        return effort_norm, True

    if think_norm:
        if think_norm == "enabled":
            return "high", True
        if think_norm in NON_OFF_THINKING_LEVELS:
            return think_norm, True
        msg = f"unsupported thinking value: {thinking!r}"
        raise ValueError(msg)

    hint = f"{model} {base_url}".lower()
    if "glm" in hint or "zai" in hint:
        return "high", True
    return "off", False


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
        thinking_out = ""
        if thinking.strip() or reasoning_effort.strip():
            thinking_out, _ = _resolve_thinking(thinking, reasoning_effort)
        return None, {
            "provider": "",
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
    api = _resolve_api(protocol, use_anthropic)
    thinking_level, reasoning = _resolve_thinking(
        thinking,
        reasoning_effort,
        model=clean_model,
        base_url=base_url,
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
        DEFAULT_CONTEXT_WINDOW,
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
    if api == "openai-completions" and (
        "glm" in clean_model.lower() or "zai" in base_url.lower()
    ):
        model_entry["compat"] = {"thinkingFormat": "zai"}

    payload: dict[str, object] = {
        "providers": {
            "custom-gateway": {
                "baseUrl": base_url,
                "api": api,
                "apiKey": "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN",
                "models": [model_entry],
            },
        },
    }
    outputs = {
        "provider": "custom-gateway",
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
