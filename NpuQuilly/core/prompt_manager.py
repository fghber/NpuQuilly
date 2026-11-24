"""Prompt templates for the writing actions."""
import json
from pathlib import Path

DEFAULTS = Path(__file__).parent.parent / "resources" / "default_prompts.json"

ACTIONS = ("grammar_check", "rewrite", "summarize", "custom")


class PromptManager:
    def __init__(self, path: Path = DEFAULTS):
        self.path = Path(path)
        self.prompts = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, action: str):
        if action not in self.prompts:
            raise KeyError(f"Unknown action '{action}'. Available: {sorted(self.prompts)}")
        return self.prompts[action]

    def temperature(self, action: str) -> float:
        return float(self.get(action).get("temperature", 0.5))
