"""Global hotkeys via pynput. All imports lazy so --smoke works headless."""
from typing import Callable


def parse_combo(combo: str):
    """Return the keys pynput matches, independent of their order."""
    from pynput import keyboard
    return frozenset(keyboard.HotKey.parse(combo))


def validate_combo(combo: str) -> bool:
    """True if pynput can parse this canonical hotkey string."""
    try:
        parse_combo(combo)
        return True
    except (TypeError, ValueError):
        return False


class HotkeyManager:
    def __init__(self, hotkeys: dict, on_popup: Callable, on_direct: Callable):
        self.hotkeys = hotkeys
        self.on_popup = on_popup
        self.on_direct = on_direct
        self._listener = None
        self.error: str | None = None

    def _mapping(self):
        def wrap(fn):
            def inner():
                fn()
            return inner

        def add(mapping: dict, combo: str | None, label: str, fn):
            if not combo:
                return
            if not validate_combo(combo):
                print(f"[npuquilly] WARNING: skipping invalid hotkey {label}={combo!r} "
                      f"(fix in Settings or {self._config_hint()})")
                return
            mapping[combo] = wrap(fn)

        m: dict = {}
        add(m, self.hotkeys.get("popup"), "popup", self.on_popup)
        for action in ("grammar", "rewrite"):
            key = self.hotkeys.get(action)
            act = action + "_check" if action == "grammar" else action
            add(m, key, action, lambda a=act: self.on_direct(a))
        add(m, self.hotkeys.get("repeat"), "repeat", lambda: self.on_direct("__repeat__"))
        return m

    @staticmethod
    def _config_hint() -> str:
        try:
            from core.config_manager import config_path
            return str(config_path())
        except Exception:
            return "config.json"

    def start(self):
        from pynput import keyboard
        try:
            self._listener = keyboard.GlobalHotKeys(self._mapping())
            self._listener.start()
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            print(f"[npuquilly] ERROR: hotkey listener failed to start: {self.error}")
            print("[npuquilly] Tray keeps running — open Settings to change hotkeys.")
            self._listener = None

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
                self._listener.join(timeout=1)
            except Exception:
                pass
            self._listener = None
