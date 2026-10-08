"""Normalize the public llm-* inputs before selecting a Qwen provider."""

from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class ConfigurationError(ValueError):
    """Configuration cannot satisfy the unattended model contract."""


EFFORTS = {"minimal", "low", "medium", "high", "max"}
PROTECTED = {
    "model",
    "messages",
    "input",
    "instructions",
    "system",
    "tools",
    "functions",
    "function_call",
    "tool_choice",
    "parallel_tool_calls",
    "stream",
    "stream_options",
    "api_key",
    "apiKey",
    "base_url",
    "baseURL",
    "headers",
    "authorization",
    "auth",
    "previous_response_id",
}
HEADER = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        msg = f"{name} must be numeric"
        raise ConfigurationError(msg)
    try:
        number = float(value)
    except (ValueError, TypeError):
        msg = f"{name} must be numeric"
        raise ConfigurationError(msg) from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        msg = f"{name} is out of range"
        raise ConfigurationError(msg)
    return number


def _boolean(value: str, name: str) -> bool:
    if value.lower() in {"true", "1", "yes"}:
        return True
    if value.lower() in {"", "false", "0", "no"}:
        return False
    msg = f"{name} must be a boolean string"
    raise ConfigurationError(msg)


@dataclass(frozen=True)
class ModelConfig:
    protocol: str
    base_url: str
    model: str
    tokens: tuple[str, ...] = field(repr=False)
    timeout_seconds: float
    body: dict
    headers: dict[str, str] = field(repr=False)
    auth_header: str
    context_window_size: int | None = None
    modalities: dict[str, bool] | None = None

    def request_headers(self, token: str) -> dict[str, str]:
        name = self.auth_header or (
            "x-api-key" if self.protocol == "anthropic" else "Authorization"
        )
        value = f"Bearer {token}" if name.lower() == "authorization" else token
        return {**self.headers, name: value}

    def generation_config(self, token: str) -> dict:
        body = dict(self.body)
        if self.protocol == "openai-responses" and "max_output_tokens" in body:
            body["max_tokens"] = body.pop("max_output_tokens")
        sampling = {
            key: body.pop(key)
            for key in ("temperature", "top_p", "top_k", "max_tokens")
            if key in body
            and not (self.protocol == "openai-responses" and key == "top_k")
        }
        result = {
            "timeout": round(self.timeout_seconds * 1000),
            "maxRetries": 2,
            "samplingParams": sampling,
            "customHeaders": self.request_headers(token),
        }
        if self.context_window_size is not None:
            result["contextWindowSize"] = self.context_window_size
        if self.modalities is not None:
            result["modalities"] = dict(self.modalities)
        if self.protocol == "openai-responses":
            effort = body.pop("reasoning_effort", None)
            reasoning = body.pop("reasoning", None)
            if reasoning is not None:
                result["reasoning"] = reasoning
            elif effort:
                result["reasoning"] = {"effort": effort}
        if self.protocol == "anthropic":
            result["reasoning"] = False
            # The pinned Anthropic generator ignores extra_body. Reject fields
            # it cannot map instead of accepting silently ineffective settings.
            thinking = body.pop("thinking", None)
            if thinking:
                result["reasoning"] = (
                    False
                    if thinking["type"] == "disabled"
                    else {"budget_tokens": thinking["budget_tokens"]}
                )
        if body:
            result["extra_body"] = body
        return result


def normalize_inputs(inputs: Mapping[str, str]) -> ModelConfig:
    """Validate the reusable llm-* string interface; never read ambient secrets."""
    names = {
        "url",
        "model",
        "protocol",
        "use-anthropic",
        "thinking",
        "thinking-clear",
        "temperature",
        "top-p",
        "reasoning-effort",
        "timeout",
        "context-window-size",
        "modalities",
        "auth-header",
        "extra-headers",
        "extra-body",
        "auth-token",
    }
    if any(key not in {f"llm-{name}" for name in names} for key in inputs):
        msg = "Unknown model input"
        raise ConfigurationError(msg)
    if any(not isinstance(value, str) for value in inputs.values()):
        msg = "Model inputs must be strings"
        raise ConfigurationError(msg)
    values = {key: value.strip() for key, value in inputs.items()}
    protocol = values.get("llm-protocol", "").lower()
    if not protocol:
        protocol = (
            "anthropic"
            if _boolean(values.get("llm-use-anthropic", ""), "llm-use-anthropic")
            else "openai"
        )
    if protocol not in {"openai", "openai-responses", "anthropic"}:
        msg = "Unsupported llm-protocol"
        raise ConfigurationError(msg)
    model = values.get("llm-model", "")
    if not model or any(char.isspace() for char in model):
        msg = "llm-model is required and cannot contain whitespace"
        raise ConfigurationError(msg)
    url = urlsplit(values.get("llm-url", ""))
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        msg = "llm-url must be an HTTP base URL without credentials, query, or fragment"
        raise ConfigurationError(msg)
    path = url.path.rstrip("/")
    for endpoint in ("/chat/completions", "/responses", "/messages"):
        if path.endswith(endpoint):
            path = path[: -len(endpoint)]
            break
    if protocol == "anthropic" and path.endswith("/v1"):
        path = path[:-3]
    elif protocol == "openai-responses" and not path.endswith("/v1"):
        path += "/v1"
    elif protocol != "anthropic" and not path:
        path = "/v1"
    base_url = urlunsplit((url.scheme, url.netloc, path, "", ""))
    tokens = tuple(
        dict.fromkeys(
            token.strip()
            for token in values.get("llm-auth-token", "").split(",")
            if token.strip()
        ),
    )
    if not tokens or any(any(char.isspace() for char in token) for token in tokens):
        msg = "llm-auth-token requires tokens without embedded whitespace"
        raise ConfigurationError(msg)
    timeout = _number(
        values.get("llm-timeout") or "3600",
        "llm-timeout",
        0.001,
        2147483,
    )
    context_window_size = None
    if value := values.get("llm-context-window-size"):
        # Qwen stores this as a JavaScript number; require an exact integer.
        if not re.fullmatch(r"[0-9]+", value) or not 0 < int(value) <= 2**53 - 1:
            msg = "llm-context-window-size must be a positive safe integer"
            raise ConfigurationError(msg)
        context_window_size = int(value)
    modalities = None
    if value := values.get("llm-modalities"):
        try:
            modalities = json.loads(value)
        except ValueError:
            msg = "llm-modalities must be a JSON object"
            raise ConfigurationError(msg) from None
        if (
            not isinstance(modalities, dict)
            or set(modalities) - {"image", "pdf", "audio", "video"}
            or any(type(enabled) is not bool for enabled in modalities.values())
        ):
            msg = "llm-modalities requires image, pdf, audio, or video boolean fields"
            raise ConfigurationError(msg)
        # Qwen 0.25.0 ModelRegistry replaces all MiniMax-M3 modality overrides.
        if model.lower().startswith("minimax-m3"):
            msg = (
                "llm-modalities overrides are unsupported for MiniMax-M3 by pinned Qwen"
            )
            raise ConfigurationError(msg)
    try:
        extra = json.loads(
            values.get("llm-extra-body") or "{}",
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, TypeError):
        msg = "llm-extra-body must be a JSON object"
        raise ConfigurationError(msg) from None
    if not isinstance(extra, dict) or PROTECTED.intersection(extra):
        msg = "llm-extra-body must be an object without protected request fields"
        raise ConfigurationError(msg)
    body = {}
    if protocol == "openai":
        thinking = (values.get("llm-thinking") or "disabled").lower()
        if thinking not in {"enabled", "disabled"}:
            msg = "llm-thinking must be enabled or disabled"
            raise ConfigurationError(msg)
        body = {
            "temperature": 0.4,
            "top_p": 0.9,
            "thinking": {
                "type": thinking,
                "clear_thinking": _boolean(
                    values.get("llm-thinking-clear", "false"),
                    "llm-thinking-clear",
                ),
            },
        }
        # Explicit provider controls replace the corresponding convenience
        # setting. Preserve thinking only when the extra body supplies it too.
        if "enable_thinking" in extra:
            body.pop("thinking")
    elif values.get("llm-thinking") or values.get("llm-thinking-clear"):
        msg = "llm-thinking and llm-thinking-clear require openai"
        raise ConfigurationError(msg)
    for name, key, maximum in (
        ("llm-temperature", "temperature", 1 if protocol == "anthropic" else 2),
        ("llm-top-p", "top_p", 1),
    ):
        if values.get(name):
            body[key] = _number(values[name], name, 0, maximum)
    effort = values.get("llm-reasoning-effort", "").lower()
    if effort:
        if effort not in EFFORTS:
            msg = "Unsupported llm-reasoning-effort"
            raise ConfigurationError(msg)
        body["reasoning_effort"] = effort
    body.update(extra)
    _validate_body(protocol, body, model)
    auth_header = values.get("llm-auth-header", "")
    if auth_header and not HEADER.fullmatch(auth_header):
        msg = "Invalid llm-auth-header"
        raise ConfigurationError(msg)
    headers = {}
    for item in filter(None, values.get("llm-extra-headers", "").split(",")):
        key, separator, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if (
            not separator
            or not HEADER.fullmatch(key)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            msg = "llm-extra-headers must use K=V pairs"
            raise ConfigurationError(msg)
        if key.lower() in {
            "authorization",
            "x-api-key",
            "host",
            "content-length",
            auth_header.lower(),
        } or key.lower() in {name.lower() for name in headers}:
            msg = "Extra headers cannot replace authentication or transport headers"
            raise ConfigurationError(msg)
        headers[key] = value
    return ModelConfig(
        protocol,
        base_url,
        model,
        tokens,
        timeout,
        body,
        headers,
        auth_header,
        context_window_size,
        modalities,
    )


def _validate_body(protocol: str, body: dict, model: str) -> None:
    for key, maximum in (
        ("temperature", 1 if protocol == "anthropic" else 2),
        ("top_p", 1),
    ):
        if key in body:
            body[key] = _number(body[key], key, 0, maximum)
    if "reasoning_effort" in body and (
        not isinstance(body["reasoning_effort"], str)
        or body["reasoning_effort"] not in EFFORTS
    ):
        msg = "Unsupported reasoning_effort"
        raise ConfigurationError(msg)
    if protocol == "openai" and "thinking" in body:
        thinking = body["thinking"]
        if (
            not isinstance(thinking, dict)
            or not isinstance(thinking.get("type"), str)
            or thinking["type"] not in {"enabled", "disabled"}
            or (
                "clear_thinking" in thinking
                and type(thinking["clear_thinking"]) is not bool
            )
        ):
            msg = "Invalid OpenAI thinking configuration"
            raise ConfigurationError(msg)
    if protocol == "openai" and "enable_thinking" in body:
        if type(body["enable_thinking"]) is not bool:
            msg = "enable_thinking must be a boolean"
            raise ConfigurationError(msg)
        if "thinking" in body and (
            (body["thinking"]["type"] == "enabled") != body["enable_thinking"]
        ):
            msg = "Conflicting explicit thinking controls"
            raise ConfigurationError(msg)
    if protocol == "openai-responses":
        # Qwen 0.25.0 populates these before extra_body, which cannot replace them.
        if "store" in body and body["store"] is not False:
            msg = "The pinned Responses adapter requires store=false"
            raise ConfigurationError(msg)
        if "prompt_cache_key" in body:
            msg = "The pinned Responses adapter controls prompt_cache_key"
            raise ConfigurationError(msg)
        if "include" in body and body["include"] != ["reasoning.encrypted_content"]:
            msg = (
                "The pinned Responses adapter reserves include for encrypted reasoning"
            )
            raise ConfigurationError(msg)
        if any(
            key in body for key in ("thinking", "enable_thinking", "clear_thinking")
        ):
            msg = "Thinking fields require openai or native Anthropic configuration"
            raise ConfigurationError(msg)
        if "reasoning" in body:
            reasoning = body["reasoning"]
            if (
                not isinstance(reasoning, dict)
                or set(reasoning) != {"effort"}
                or not isinstance(reasoning["effort"], str)
                or reasoning["effort"] not in EFFORTS
            ):
                msg = "Unsupported Responses reasoning configuration"
                raise ConfigurationError(msg)
    if (
        protocol == "openai-responses"
        and "max_output_tokens" in body
        and "max_tokens" in body
        and body["max_tokens"] != body["max_output_tokens"]
    ):
        msg = "Conflicting Responses output limits"
        raise ConfigurationError(msg)
    if protocol == "anthropic":
        # Mirror the pinned CLI's known model gates; it otherwise silently drops
        # these explicit settings. See Qwen core/anthropic-reasoning.ts.
        version = re.search(
            r"claude-(?:opus|sonnet|haiku|fable|mythos)-(\d+)(?:[-.](\d{1,2})(?!\d))?",
            model.lower(),
        )
        version_pair = (
            tuple(int(part or 0) for part in version.groups()) if version else (0, 0)
        )
        if version_pair >= (4, 8) and "temperature" in body:
            msg = "The pinned Anthropic adapter drops temperature for this model"
            raise ConfigurationError(msg)
        if (
            version_pair >= (4, 7)
            and isinstance(body.get("thinking"), dict)
            and body["thinking"].get("type") == "enabled"
        ):
            msg = "The pinned Anthropic adapter drops manual thinking for this model"
            raise ConfigurationError(msg)
        if set(body) - {"temperature", "top_p", "top_k", "max_tokens", "thinking"}:
            msg = "Unsupported Anthropic body fields"
            raise ConfigurationError(msg)
        thinking = body.get("thinking")
        if thinking is not None:
            if (
                not isinstance(thinking, dict)
                or not isinstance(thinking.get("type"), str)
                or thinking.get("type")
                not in {
                    "enabled",
                    "disabled",
                }
            ):
                msg = "Unsupported Anthropic thinking"
                raise ConfigurationError(msg)
            expected = (
                {"type", "budget_tokens"} if thinking["type"] == "enabled" else {"type"}
            )
            if set(thinking) != expected:
                msg = "Unsupported Anthropic thinking fields"
                raise ConfigurationError(msg)
            if thinking["type"] == "enabled":
                if "temperature" in body and body["temperature"] != 1:
                    msg = "Anthropic thinking requires temperature 1"
                    raise ConfigurationError(msg)
                budget = thinking["budget_tokens"]
                if type(budget) is not int or budget < 1024:
                    msg = "Anthropic thinking budget must be at least 1024"
                    raise ConfigurationError(msg)
    for key in ("max_tokens", "max_output_tokens", "top_k"):
        if key in body and (type(body[key]) is not int or body[key] <= 0):
            msg = f"{key} must be a positive integer"
            raise ConfigurationError(msg)


def _probe(config: ModelConfig, token: str, timeout: float) -> bool:
    body = {"model": config.model}
    headers = {"Content-Type": "application/json", **config.request_headers(token)}
    if config.protocol == "anthropic":
        path = "/v1/messages"
        body.update(messages=[{"role": "user", "content": "Reply OK."}], max_tokens=1)
        headers["anthropic-version"] = "2023-06-01"
    elif config.protocol == "openai-responses":
        path = "/responses"
        body.update(input="Reply OK.", max_output_tokens=16)
    else:
        path = "/chat/completions"
        body.update(messages=[{"role": "user", "content": "Reply OK."}], max_tokens=1)
    request = urllib.request.Request(  # noqa: S310 - normalize_inputs permits HTTP(S) only.
        config.base_url + path,
        json.dumps(body).encode(),
        headers,
    )

    # Never follow a provider redirect with credentials to another origin.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    with urllib.request.build_opener(NoRedirect).open(
        request,
        timeout=timeout,
    ) as response:
        result = json.load(response)
        key = (
            "content"
            if config.protocol == "anthropic"
            else "output"
            if config.protocol == "openai-responses"
            else "choices"
        )
        return (
            isinstance(result, dict)
            and isinstance(result.get(key), list)
            and bool(result[key])
        )


def select_token(
    config: ModelConfig,
    *,
    probe: Callable = _probe,
    mask: Callable[[str], None] = lambda _: None,
) -> str:
    """Mask every candidate, then try each once with a bounded native request."""
    for token in config.tokens:
        mask(token)
    if len(config.tokens) == 1:
        return config.tokens[0]
    expires = time.monotonic() + min(30, config.timeout_seconds)
    for token in config.tokens:
        remaining = expires - time.monotonic()
        if remaining <= 0:
            break
        result = queue.Queue()
        probe_timeout = min(15, remaining)

        def attempt(candidate=token, timeout=probe_timeout, outcome=result):
            try:
                outcome.put(probe(config, candidate, timeout))
            except (OSError, ValueError):
                outcome.put(False)

        # A socket timeout alone does not bound a drip-fed response.
        # Daemon workers cannot keep a failed controller alive at process exit.
        threading.Thread(target=attempt, daemon=True).start()
        try:
            if result.get(timeout=min(15, remaining)):
                return token
        except queue.Empty:
            continue
    msg = "No token passed the provider probe"
    raise ConfigurationError(msg)
