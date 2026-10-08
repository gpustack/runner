"""Minimal stdio MCP research fixture. No network or credentials."""

import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message["method"]
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fixture", "version": "1"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "research",
                    "description": "Read fixture release evidence",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            ],
        }
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "MCP_EVIDENCE_LOADED"}]}
    else:
        result = {}
    print(
        json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}),
        flush=True,
    )
