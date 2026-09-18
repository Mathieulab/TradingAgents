"""Persist actual prompts, not provider credentials or HTTP headers."""

import hashlib
from pathlib import Path
from threading import Lock

from langchain_core.callbacks import BaseCallbackHandler


class PromptAudit(BaseCallbackHandler):
    def __init__(self):
        self.calls = []
        self.lock = Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        with self.lock:
            self.calls.append(
                {
                    "run_id": str(run_id),
                    "messages": [
                        [{"type": message.type, "content": message.content} for message in batch]
                        for batch in messages
                    ],
                }
            )


def source_manifest():
    root = Path(__file__).resolve().parents[2]
    files = list((root / "tradingagents/agents").rglob("*.py"))
    files += list((root / "finance_lab/astra").glob("*.py"))
    files += [
        root / name
        for name in (
            "tradingagents/graph/setup.py",
            "tradingagents/graph/conditional_logic.py",
            "tradingagents/integrations/astra_context.py",
            "finance_lab/ftmo/engine.py",
            "finance_lab/ftmo/config.py",
            "finance_lab/ftmo/data.py",
        )
    ]
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }
