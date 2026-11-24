"""JSON config in %APPDATA%/NpuQuilly/config.json (fallback: user home)."""
import json
import os
from copy import deepcopy
from pathlib import Path

CONFIG_VERSION = 2

DEFAULTS = {
    "base_url": "http://127.0.0.1:8000/v1",
    "api_key": "dummy",
    "model": "grammar-fast",
    "device": "GPU",
    "hotkeys": {
        # NOTE: popup was <ctrl>+<space> in v1 — hijacked by IME/VS Code on many
        # machines. v2 default is Win+Shift+Q (no known OS/app binding).
        "popup": "<cmd>+<shift>+q",
        "repeat": "<ctrl>+<shift>+<space>",
        "grammar": "<ctrl>+<shift>+g",
        "rewrite": "<ctrl>+<shift>+r",
    },
    "last_action": "grammar_check",
    "direct_paste": False,  # review model corrections before replacing selected text
    # Optional per-action server aliases, e.g. {"rewrite": "rewrite-alt"}.
    # Empty = global "model" for every action.
    "action_models": {},
    "config_version": CONFIG_VERSION,
}

# v1 values auto-migrated on load (only when untouched = still the old default).
_OLD_DEFAULTS = {"popup": "<ctrl>+<space>"}


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "NpuQuilly"
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


class ConfigManager:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_path()
        self.data = deepcopy(DEFAULTS)
        existed = self.path.exists()
        file_version = 1
        if existed:
            try:
                file_data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(file_data, dict):
                    raise ValueError("Config must be an object")
                file_version = file_data.get("config_version", 1)
                if not isinstance(file_version, int):
                    file_version = 1
                self.data.update(file_data)
            except Exception:
                pass
        hotkeys = deepcopy(DEFAULTS["hotkeys"])
        if isinstance(self.data.get("hotkeys"), dict):
            hotkeys.update(self.data["hotkeys"])
        self.data["hotkeys"] = hotkeys
        if self._migrate(file_version) and existed:
            self.save()

    def _migrate(self, file_version: int) -> bool:
        """Apply pending migrations. Returns True if data changed."""
        changed = False
        if file_version < CONFIG_VERSION:
            hk = dict(self.data.get("hotkeys") or {})
            for k, old in _OLD_DEFAULTS.items():
                if hk.get(k) == old:
                    hk[k] = DEFAULTS["hotkeys"][k]
                    changed = True
            if hk != self.data.get("hotkeys"):
                self.data["hotkeys"] = hk
                changed = True
            self.data["config_version"] = CONFIG_VERSION
            changed = True
        return changed

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
