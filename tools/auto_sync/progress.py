"""Turn Qwen stream-json bytes into concise, redacted progress and a token guard."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from tools.auto_sync.proposal import ordered_secrets

if TYPE_CHECKING:
    from collections.abc import Callable

HEARTBEAT_SECONDS = 30
MAX_TEXT = 160
MAX_PENDING = 64 * 1024 * 1024  # Bound a never-terminated line.


def _count(value) -> int:
    return value if type(value) is int and value > 0 else 0


def message_tokens(usage) -> int:
    """
    Count one message's reported tokens.

    Qwen 0.25.0 maps prompt/candidate/total counts to input_tokens,
    output_tokens, and total_tokens; cachedContentTokenCount becomes
    cache_read_input_tokens, a subset of the prompt count, so it is never
    added.
    """
    if not isinstance(usage, dict):
        return 0
    return _count(usage.get("total_tokens")) or (
        _count(usage.get("input_tokens")) + _count(usage.get("output_tokens"))
    )


class ProgressObserver:
    """
    Parse complete LF-framed events; emit one safe line per milestone.

    Usage arrives after a request, so this guards reported usage only. It cannot
    bound provider billing or requests already issued.
    """

    def __init__(
        self,
        *,
        emit: Callable[[str], None],
        secrets=(),
        max_tokens: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        heartbeat: float = HEARTBEAT_SECONDS,
    ) -> None:
        self._emit = emit
        self._secrets = ordered_secrets(secrets)
        self.max_tokens = max_tokens
        self._clock = clock
        self._heartbeat = heartbeat
        self._started = self._last = clock()
        self._pending = b""
        self._usage: dict[str, int] = {}
        self._tools: dict[str, str] = {}
        self.tokens = 0
        self.exceeded = False

    @property
    def stop_requested(self) -> bool:
        return self.exceeded

    def feed(self, data: bytes) -> None:
        """Consume appended bytes; split only on the protocol LF."""
        self._pending += data
        *lines, self._pending = self._pending.split(b"\n")
        if len(self._pending) > MAX_PENDING:
            self._pending = b""
        for raw in lines:
            self._event(raw.decode("utf-8", errors="replace"))

    def tick(self) -> None:
        """Report elapsed time after a quiet period; this is not model liveness."""
        if self._clock() - self._last >= self._heartbeat:
            self._line("supervised process running; no new event")

    def _clean(self, value, limit: int = MAX_TEXT) -> str:
        text = value if isinstance(value, str) else ""
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        # Controls, ANSI escapes, CR, and Unicode separators must not form lines.
        text = "".join(c if c.isprintable() else " " for c in text)
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _line(self, message: str) -> None:
        now = self._clock()
        self._last = now
        elapsed = int(now - self._started)
        stamp = f"{elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}"
        try:
            # The fixed prefix keeps a line from starting with a workflow command.
            self._emit(f"auto-sync progress [{stamp} tokens={self.tokens}] {message}")
        except (OSError, ValueError):
            self._emit = lambda _: None  # A closed log must not stop the agent.

    def _event(self, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        self._last = self._clock()
        kind = event.get("type")
        if kind == "system" and event.get("subtype") in {"init", "session_start"}:
            self._line("session started")
        elif kind == "assistant":
            self._assistant(event)
        elif kind == "user":
            self._results(event)
        elif kind == "result":
            self._line(
                "session finished" + (" with error" if event.get("is_error") else ""),
            )

    def _assistant(self, event: dict) -> None:
        message = event.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = self._clean(block.get("text"))
                # The final answer is the proposal document; never echo it.
                if text and not text.startswith(("{", "[", "```")):
                    self._line("assistant: " + text)
            elif block.get("type") == "tool_use":
                name = self._clean(block.get("name"), 64) or "tool"
                if isinstance(block.get("id"), str):
                    self._tools[block["id"]] = name
                self._line(f"tool started: {name}")
        identity = message.get("id") or event.get("uuid")
        if isinstance(identity, str):
            self._add(identity, message_tokens(message.get("usage")))

    def _results(self, event: dict) -> None:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                name = self._tools.pop(str(block.get("tool_use_id")), "tool")
                failed = block.get("is_error") is True
                self._line(f"tool {'failed' if failed else 'completed'}: {name}")

    def _add(self, identity: str, tokens: int) -> None:
        # One message may be re-emitted; count only growth of its reported usage.
        grown = tokens - self._usage.get(identity, 0)
        if grown <= 0:
            return
        self._usage[identity] = tokens
        self.tokens += grown
        if self.max_tokens is not None and self.tokens >= self.max_tokens:
            self.exceeded = True
            self._line(
                f"session token budget exceeded: {self.tokens} reported"
                f" >= {self.max_tokens}; stopping",
            )
