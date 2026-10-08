"""Capture Qwen's effective context window from its Stop hook."""

import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(json.dumps(json.load(sys.stdin)))
print("{}")
