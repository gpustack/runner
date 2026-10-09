"""Local streaming model endpoints with deterministic tool turns."""

import json
import select
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL = json.dumps({"status": "unchanged", "summary": "Fixture complete"})
# Optional per-session final texts for multi-session controllers; the last
# entry repeats for later sessions. None keeps FINAL for every session.
FINALS = None


def scripted(*phases: list[str]) -> list[str]:
    """
    Flatten per-phase final-reply sequences into FINALS entries.

    Research dispatches one fresh session per stage and per repair round, so a
    phase that must first fail then succeed lists its finals in dispatch order,
    for example scripted([invalid, valid], [proposal]).
    """
    return [text for phase in phases for text in phase]


@contextmanager
def endpoint(protocol, *, delay=0, tools=True, calls=None, path=None):
    requests = []
    sessions = []
    expected_path = (
        path
        or {
            "openai": "/v1/chat/completions",
            "openai-responses": "/v1/responses",
            "anthropic": "/v1/messages",
        }[protocol]
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                    "time": time.monotonic(),
                },
            )
            if self.path != expected_path:
                self.send_error(404)
                return
            if not body.get("stream"):
                key = {
                    "openai": "choices",
                    "openai-responses": "output",
                    "anthropic": "content",
                }[protocol]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({key: [{"text": "OK"}]}).encode())
                return
            started = time.monotonic()
            while time.monotonic() - started < delay:
                readable, _, _ = select.select([self.connection], [], [], 0.01)
                if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                    requests[-1]["closed_after"] = time.monotonic() - started
                    return
            # A request without assistant or tool history starts a new session.
            history = body.get("messages") or body.get("input") or []
            continuing = any(
                item.get("role") in {"assistant", "tool"}
                or item.get("type") == "function_call_output"
                for item in history
                if isinstance(item, dict)
            )
            if not continuing or not sessions:
                sessions.append([])
            sessions[-1].append(body)
            turn = len(sessions[-1])
            session = len(sessions) - 1
            finals = FINALS or [FINAL]
            final_text = finals[min(session, len(finals) - 1)]
            names = [
                tool.get("name", tool.get("function", {}).get("name"))
                for tool in body.get("tools", [])
            ]
            name = (
                "skill"
                if turn == 1
                else next(
                    (name for name in names if name and "research" in name),
                    "missing_mcp",
                )
            )
            args = {"skill": "fixture-release"} if turn == 1 else {}
            call = tools and turn < 3
            session_calls = calls.get(session, []) if isinstance(calls, dict) else calls
            if session_calls is not None:
                call = turn <= len(session_calls)
                if call:
                    name, args = session_calls[turn - 1]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            try:

                def event(value, kind=None):
                    if kind:
                        self.wfile.write(f"event: {kind}\n".encode())
                    self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
                    self.wfile.flush()

                if protocol == "openai":
                    delta = {"role": "assistant"}
                    if call:
                        delta["tool_calls"] = [
                            {
                                "index": 0,
                                "id": f"call_{turn}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args),
                                },
                            },
                        ]
                    else:
                        delta["content"] = final_text
                    event(
                        {
                            "id": f"chat_{turn}",
                            "object": "chat.completion.chunk",
                            "model": body["model"],
                            "choices": [
                                {"index": 0, "delta": delta, "finish_reason": None},
                            ],
                        },
                    )
                    event(
                        {
                            "id": f"chat_{turn}",
                            "object": "chat.completion.chunk",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": "tool_calls" if call else "stop",
                                },
                            ],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 10,
                                "total_tokens": 20,
                            },
                        },
                    )
                    self.wfile.write(b"data: [DONE]\n\n")
                elif protocol == "anthropic":
                    event(
                        {
                            "type": "message_start",
                            "message": {
                                "id": f"msg_{turn}",
                                "type": "message",
                                "role": "assistant",
                                "model": body["model"],
                                "content": [],
                                "usage": {"input_tokens": 10, "output_tokens": 0},
                            },
                        },
                        "message_start",
                    )
                    block = (
                        {
                            "type": "tool_use",
                            "id": f"call_{turn}",
                            "name": name,
                            "input": {},
                        }
                        if call
                        else {"type": "text", "text": ""}
                    )
                    event(
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": block,
                        },
                        "content_block_start",
                    )
                    delta = (
                        {"type": "input_json_delta", "partial_json": json.dumps(args)}
                        if call
                        else {"type": "text_delta", "text": final_text}
                    )
                    event(
                        {"type": "content_block_delta", "index": 0, "delta": delta},
                        "content_block_delta",
                    )
                    event(
                        {"type": "content_block_stop", "index": 0},
                        "content_block_stop",
                    )
                    event(
                        {
                            "type": "message_delta",
                            "delta": {
                                "stop_reason": "tool_use" if call else "end_turn",
                                "stop_sequence": None,
                            },
                            "usage": {"output_tokens": 10},
                        },
                        "message_delta",
                    )
                    event({"type": "message_stop"}, "message_stop")
                else:
                    response = {
                        "id": f"resp_{turn}",
                        "object": "response",
                        "status": "in_progress",
                        "model": body["model"],
                        "output": [],
                    }
                    event(
                        {"type": "response.created", "response": response},
                        "response.created",
                    )
                    if call:
                        item = {
                            "type": "function_call",
                            "id": f"fc_{turn}",
                            "call_id": f"call_{turn}",
                            "name": name,
                            "arguments": "",
                        }
                        event(
                            {
                                "type": "response.output_item.added",
                                "output_index": 0,
                                "item": item,
                            },
                            "response.output_item.added",
                        )
                        event(
                            {
                                "type": "response.function_call_arguments.delta",
                                "item_id": item["id"],
                                "output_index": 0,
                                "delta": json.dumps(args),
                            },
                            "response.function_call_arguments.delta",
                        )
                        item = {
                            **item,
                            "arguments": json.dumps(args),
                            "status": "completed",
                        }
                        event(
                            {
                                "type": "response.function_call_arguments.done",
                                "item_id": item["id"],
                                "output_index": 0,
                                "arguments": json.dumps(args),
                            },
                            "response.function_call_arguments.done",
                        )
                    else:
                        item = {
                            "type": "message",
                            "id": f"msg_{turn}",
                            "role": "assistant",
                            "content": [],
                        }
                        event(
                            {
                                "type": "response.output_item.added",
                                "output_index": 0,
                                "item": item,
                            },
                            "response.output_item.added",
                        )
                        event(
                            {
                                "type": "response.content_part.added",
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "part": {
                                    "type": "output_text",
                                    "text": "",
                                    "annotations": [],
                                },
                            },
                            "response.content_part.added",
                        )
                        event(
                            {
                                "type": "response.output_text.delta",
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "delta": final_text,
                            },
                            "response.output_text.delta",
                        )
                        event(
                            {
                                "type": "response.output_text.done",
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "text": final_text,
                            },
                            "response.output_text.done",
                        )
                        item = {
                            **item,
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": final_text,
                                    "annotations": [],
                                },
                            ],
                        }
                    event(
                        {
                            "type": "response.output_item.done",
                            "output_index": 0,
                            "item": item,
                        },
                        "response.output_item.done",
                    )
                    response.update(
                        status="completed",
                        output=[item],
                        usage={
                            "input_tokens": 10,
                            "output_tokens": 10,
                            "total_tokens": 20,
                        },
                    )
                    event(
                        {"type": "response.completed", "response": response},
                        "response.completed",
                    )
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
