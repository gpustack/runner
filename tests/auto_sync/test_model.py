# ruff: noqa: PLR2004, S105
# Imports follow the repository root setup; all credentials are fixture values.
"""Model inputs must have one meaning before Qwen provider mapping."""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.auto_sync.model import ConfigurationError, normalize_inputs, select_token


def inputs(**kwargs):
    return {
        "llm-url": "http://127.0.0.1:1234/v1/chat/completions",
        "llm-model": "fixture-model",
        "llm-auth-token": " fake-first, ,fake-second ",
        **kwargs,
    }


@pytest.mark.parametrize(
    "protocol,suffix",
    [("openai", "/v1"), ("openai-responses", "/v1"), ("anthropic", "")],
)
def test_protocol_paths_and_mapping(protocol, suffix):
    config = normalize_inputs(
        inputs(
            **{
                "llm-protocol": protocol,
                "llm-url": "http://127.0.0.1:1234/v1",
                "llm-timeout": "1.25",
            },
        ),
    )
    assert config.base_url == "http://127.0.0.1:1234" + suffix
    assert config.tokens == ("fake-first", "fake-second")
    assert config.generation_config("fake-first")["timeout"] == 1250
    assert "fake-first" not in repr(config)
    if protocol != "openai":
        assert "thinking" not in config.body


@pytest.mark.parametrize("path", ["/gateway", "/gateway/v1/", "/gateway/v1/responses"])
def test_responses_prefix_normalization_is_idempotent(path):
    values = inputs(
        **{
            "llm-protocol": "openai-responses",
            "llm-url": "http://127.0.0.1:1234" + path,
        },
    )
    config = normalize_inputs(values)
    assert config.base_url == "http://127.0.0.1:1234/gateway/v1"
    assert (
        normalize_inputs({**values, "llm-url": config.base_url}).base_url
        == config.base_url
    )


@pytest.mark.parametrize("selector", ["true", "1", "YeS"])
def test_legacy_true(selector):
    assert (
        normalize_inputs(inputs(**{"llm-use-anthropic": selector})).protocol
        == "anthropic"
    )


def test_explicit_protocol_overrides_legacy_and_extra_body_wins():
    config = normalize_inputs(
        inputs(
            **{
                "llm-protocol": "OPENAI-RESPONSES",
                "llm-use-anthropic": "invalid",
                "llm-temperature": "0.9",
                "llm-reasoning-effort": "low",
                "llm-extra-body": '{"temperature":0.2,"reasoning_effort":"high"}',
            },
        ),
    )
    mapped = config.generation_config("fake-first")
    assert mapped["samplingParams"]["temperature"] == 0.2
    assert mapped["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in mapped.get("extra_body", {})


def test_chat_defaults_and_headers():
    config = normalize_inputs(
        inputs(
            **{
                "llm-auth-header": "X-Token",
                "llm-extra-headers": "X-Fixture=yes,X-Value=a=b",
            },
        ),
    )
    assert config.body == {
        "temperature": 0.4,
        "top_p": 0.9,
        "thinking": {"type": "disabled", "clear_thinking": True},
        "max_tokens": 32768,
    }
    assert (
        config.generation_config("fake-first")["customHeaders"]["X-Token"]
        == "fake-first"
    )
    assert config.headers["X-Value"] == "a=b"


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_provider_capabilities_are_optional_and_outside_http_body(protocol):
    defaults = normalize_inputs(inputs(**{"llm-protocol": protocol}))
    assert "contextWindowSize" not in defaults.generation_config("fake-first")
    assert "modalities" not in defaults.generation_config("fake-first")
    config = normalize_inputs(
        inputs(
            **{
                "llm-protocol": protocol,
                "llm-context-window-size": " 1000000 ",
                "llm-modalities": '{"image":true,"pdf":false,"audio":true,"video":false}',
            },
        ),
    )
    mapped = config.generation_config("fake-first")
    assert mapped["contextWindowSize"] == 1000000
    assert mapped["modalities"] == {
        "image": True,
        "pdf": False,
        "audio": True,
        "video": False,
    }
    assert "contextWindowSize" not in config.body
    assert "modalities" not in config.body


@pytest.mark.parametrize(
    "override,field",
    [
        *[
            ({"llm-context-window-size": value}, "llm-context-window-size")
            for value in ("0", "-1", "1.5", "1e6", "true", "NaN", "9007199254740992")
        ],
        *[
            ({"llm-modalities": value}, "llm-modalities")
            for value in (
                "[]",
                "null",
                "true",
                "{",
                '{"text":true}',
                '{"image":1}',
                '{"image":"true"}',
                '{"image":null}',
            )
        ],
    ],
)
def test_invalid_provider_capabilities_fail_before_request(override, field):
    with pytest.raises(ConfigurationError, match=field):
        normalize_inputs(inputs(**override))


@pytest.mark.parametrize("value", ["", " "])
def test_empty_provider_capabilities_leave_qwen_defaults(value):
    config = normalize_inputs(
        inputs(**{"llm-context-window-size": value, "llm-modalities": value}),
    )
    mapped = config.generation_config("fake-first")
    assert "contextWindowSize" not in mapped
    assert "modalities" not in mapped


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
@pytest.mark.parametrize("model", ["MiniMax-M3", "minimax-m3-highspeed"])
@pytest.mark.parametrize("modalities", ['{"image":false,"video":false}', "{}"])
def test_modalities_overridden_by_pinned_qwen_are_rejected(protocol, model, modalities):
    with pytest.raises(ConfigurationError, match="llm-modalities"):
        normalize_inputs(
            inputs(
                **{
                    "llm-protocol": protocol,
                    "llm-model": model,
                    "llm-modalities": modalities,
                },
            ),
        )


def test_minimax_default_capabilities_and_older_models_remain_supported():
    defaults = normalize_inputs(inputs(**{"llm-model": "MiniMax-M3"}))
    assert "modalities" not in defaults.generation_config("fake-first")
    older = normalize_inputs(
        inputs(**{"llm-model": "MiniMax-M2.7", "llm-modalities": '{"image":false}'}),
    )
    assert older.generation_config("fake-first")["modalities"] == {"image": False}


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_enable_thinking_replaces_convenience_thinking(enabled):
    config = normalize_inputs(
        inputs(
            **{
                "llm-thinking": "disabled" if enabled else "enabled",
                "llm-extra-body": json.dumps({"enable_thinking": enabled}),
            },
        ),
    )
    assert config.body["enable_thinking"] is enabled
    assert "thinking" not in config.body


@pytest.mark.parametrize("enabled", [True, False])
def test_matching_explicit_thinking_controls_are_preserved(enabled):
    extra = {
        "enable_thinking": enabled,
        "thinking": {"type": "enabled" if enabled else "disabled"},
    }
    config = normalize_inputs(inputs(**{"llm-extra-body": json.dumps(extra)}))
    assert config.body["enable_thinking"] is enabled
    assert config.body["thinking"] == {**extra["thinking"], "clear_thinking": True}


@pytest.mark.parametrize("enabled", [True, False])
def test_conflicting_explicit_thinking_controls_fail(enabled):
    extra = {
        "enable_thinking": enabled,
        "thinking": {"type": "disabled" if enabled else "enabled"},
    }
    with pytest.raises(ConfigurationError, match="Conflicting"):
        normalize_inputs(inputs(**{"llm-extra-body": json.dumps(extra)}))


def test_explicit_glm_thinking_keeps_existing_mapping():
    config = normalize_inputs(
        inputs(**{"llm-thinking": "enabled", "llm-thinking-clear": "true"}),
    )
    assert config.body["thinking"] == {"type": "enabled", "clear_thinking": True}


@pytest.mark.parametrize(
    "clear,expected",
    [("", True), ("true", True), ("false", False)],
)
def test_glm_native_thinking_receives_history_clear_default(clear, expected):
    config = normalize_inputs(
        inputs(
            **{
                "llm-model": "GLM-5.3-Flash",
                "llm-thinking-clear": clear,
                "llm-extra-body": '{"enable_thinking":true,"reasoning_effort":"max"}',
            },
        ),
    )
    assert config.body["thinking"] == {"type": "enabled", "clear_thinking": expected}
    assert config.body["enable_thinking"] is True


def test_openai_history_clear_is_enabled_by_default():
    assert normalize_inputs(inputs()).body["thinking"]["clear_thinking"] is True


def test_explicit_native_clear_choice_is_preserved():
    config = normalize_inputs(
        inputs(
            **{
                "llm-extra-body": '{"thinking":{"type":"enabled","clear_thinking":false}}',
            },
        ),
    )
    assert config.body["thinking"]["clear_thinking"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"llm-auth-token": " , "},
        {"llm-auth-token": "fake bad"},
        {"llm-model": ""},
        {"llm-url": ""},
        {"llm-url": "https://user:password@example.test/v1"},
        {"llm-timeout": "0"},
        {"llm-timeout": "NaN"},
        {"llm-temperature": "3"},
        {"llm-top-p": "-1"},
        {"llm-use-anthropic": "maybe"},
        {"llm-protocol": "gemini"},
        {"llm-thinking": "maybe"},
        {"llm-extra-body": "[]"},
        {"llm-extra-body": '{"temperature":true}'},
        {"llm-extra-body": '{"model":"other"}'},
        {"llm-extra-body": '{"messages":[]}'},
        {"llm-extra-body": '{"tools":[]}'},
        {"llm-extra-body": '{"stream":false}'},
        {"llm-extra-headers": "Authorization=leak"},
        {"llm-extra-headers": "X-Bad=one\ntwo"},
        {"llm-protocol": "anthropic", "llm-reasoning-effort": "high"},
        {"llm-protocol": "anthropic", "llm-thinking": "enabled"},
        {"llm-protocol": "anthropic", "llm-extra-body": '{"unsupported":1}'},
        {"llm-protocol": "openai-responses", "llm-thinking-clear": "false"},
    ],
)
def test_invalid_inputs_fail_before_provider_request(override):
    with pytest.raises(ConfigurationError):
        normalize_inputs(inputs(**override))


def test_token_selection_masks_every_token_and_rejects_transport_failure():
    config = normalize_inputs(inputs())
    seen, masked = [], []

    def probe(_config, token, timeout):
        seen.append((token, timeout))
        if token == "fake-first":
            msg = "transport unavailable"
            raise OSError(msg)
        return True

    assert select_token(config, probe=probe, mask=masked.append) == "fake-second"
    assert masked == ["fake-first", "fake-second"]
    assert len(seen) == 2
    with pytest.raises(ConfigurationError, match="No token"):
        select_token(config, probe=lambda *_: False)


@pytest.mark.parametrize(
    "protocol,path,key",
    [
        ("openai", "/v1/chat/completions", "choices"),
        ("openai-responses", "/v1/responses", "output"),
        ("anthropic", "/v1/messages", "content"),
    ],
)
@pytest.mark.parametrize("failure_status", [401, 402, 403, 429])
def test_real_token_probe_uses_native_protocol(protocol, path, key, failure_status):
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, self.headers["X-Token"], body))
            accepted = self.headers["X-Token"] == "fake-second"
            self.send_response(200 if accepted else failure_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {key: [{"text": "OK"}]}
                    if accepted
                    else {"error": "token unavailable"},
                ).encode(),
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = normalize_inputs(
            inputs(
                **{
                    "llm-url": f"http://127.0.0.1:{server.server_port}/v1",
                    "llm-protocol": protocol,
                    "llm-auth-header": "X-Token",
                },
            ),
        )
        assert select_token(cfg) == "fake-second"
        assert [row[0] for row in captured] == [path, path]
        assert [row[1] for row in captured] == ["fake-first", "fake-second"]
        assert all(row[2]["model"] == "fixture-model" for row in captured)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    "body",
    [
        '{"reasoning_effort":{}}',
        '{"thinking":1}',
        '{"thinking":{"type":"maybe"}}',
        '{"thinking":{"type":"enabled","clear_thinking":"false"}}',
        '{"enable_thinking":"true"}',
        '{"enable_thinking":1}',
        '{"enable_thinking":null}',
    ],
)
def test_known_extra_fields_require_correct_types(body):
    with pytest.raises(ConfigurationError):
        normalize_inputs(inputs(**{"llm-extra-body": body}))


def test_responses_native_output_limit_maps_to_sampling_limit():
    config = normalize_inputs(
        inputs(
            **{
                "llm-protocol": "openai-responses",
                "llm-extra-body": '{"max_output_tokens":2048}',
            },
        ),
    )
    assert (
        config.generation_config("fake-first")["samplingParams"]["max_tokens"] == 2048
    )


@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_max_tokens_default_reaches_every_protocol(protocol):
    config = normalize_inputs(inputs(**{"llm-protocol": protocol}))
    assert config.body["max_tokens"] == 32768
    assert (
        config.generation_config("fake-first")["samplingParams"]["max_tokens"] == 32768
    )
    config = normalize_inputs(
        inputs(**{"llm-protocol": protocol, "llm-max-tokens": " 65536 "}),
    )
    assert config.body["max_tokens"] == 65536


def test_explicit_output_limits_replace_the_default():
    config = normalize_inputs(inputs(**{"llm-extra-body": '{"max_tokens":8192}'}))
    assert config.body["max_tokens"] == 8192
    config = normalize_inputs(
        inputs(
            **{
                "llm-protocol": "openai-responses",
                "llm-extra-body": '{"max_output_tokens":8192}',
            },
        ),
    )
    assert "max_tokens" not in config.body
    assert (
        config.generation_config("fake-first")["samplingParams"]["max_tokens"] == 8192
    )
    with pytest.raises(ConfigurationError, match="Conflicting Responses"):
        normalize_inputs(
            inputs(
                **{
                    "llm-protocol": "openai-responses",
                    "llm-max-tokens": "65536",
                    "llm-extra-body": '{"max_output_tokens":8192}',
                },
            ),
        )


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "1.5", "1e6", "true", "NaN", "9007199254740992"],
)
def test_invalid_max_tokens_fail_before_request(value):
    with pytest.raises(ConfigurationError, match="llm-max-tokens"):
        normalize_inputs(inputs(**{"llm-max-tokens": value}))


def test_anthropic_thinking_cannot_silently_replace_temperature():
    with pytest.raises(ConfigurationError, match="temperature"):
        normalize_inputs(
            inputs(
                **{
                    "llm-protocol": "anthropic",
                    "llm-temperature": "0.2",
                    "llm-extra-body": '{"thinking":{"type":"enabled","budget_tokens":1024}}',
                },
            ),
        )


@pytest.mark.parametrize("field", ["functions", "function_call"])
def test_legacy_tool_control_cannot_override_policy(field):
    with pytest.raises(ConfigurationError):
        normalize_inputs(inputs(**{"llm-extra-body": json.dumps({field: []})}))


@pytest.mark.parametrize(
    "model,extra",
    [
        ("claude-opus-4-8", {"temperature": 0.2}),
        ("claude-opus-4.8", {"temperature": 0.2}),
        ("claude-sonnet-5", {"thinking": {"type": "enabled", "budget_tokens": 1024}}),
        ("claude-opus-4-7", {"thinking": {"type": "enabled", "budget_tokens": 1024}}),
    ],
)
def test_known_anthropic_settings_that_qwen_would_drop_are_rejected(model, extra):
    with pytest.raises(ConfigurationError):
        normalize_inputs(
            inputs(
                **{
                    "llm-model": model,
                    "llm-protocol": "anthropic",
                    "llm-extra-body": json.dumps(extra),
                },
            ),
        )


def test_token_selection_has_total_deadline_even_if_transport_does_not_return():
    config = normalize_inputs(inputs(**{"llm-timeout": "0.03"}))

    def stuck_probe(*_):
        time.sleep(0.5)
        return True

    started = time.monotonic()
    with pytest.raises(ConfigurationError, match="No token"):
        select_token(config, probe=stuck_probe)
    assert time.monotonic() - started < 0.2
