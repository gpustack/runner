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
        "thinking": {"type": "disabled", "clear_thinking": False},
    }
    assert (
        config.generation_config("fake-first")["customHeaders"]["X-Token"]
        == "fake-first"
    )
    assert config.headers["X-Value"] == "a=b"


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
