"""Clipboard capture + paste-back. Heavy deps imported lazily."""
import time
from uuid import uuid4


class PasteTargetChanged(RuntimeError):
    """The original window or selected text could not be verified."""


def _user32():
    import ctypes
    from ctypes import wintypes as wt
    api = ctypes.windll.user32
    api.GetForegroundWindow.restype = wt.HWND
    api.SetForegroundWindow.argtypes = [wt.HWND]
    api.SetForegroundWindow.restype = wt.BOOL
    api.IsWindow.argtypes = [wt.HWND]
    api.IsWindow.restype = wt.BOOL
    api.GetAsyncKeyState.argtypes = [ctypes.c_int]
    api.GetAsyncKeyState.restype = ctypes.c_short
    return api


def foreground_window():
    return _user32().GetForegroundWindow()


def restore_window(target) -> bool:
    api = _user32()
    if not target or not api.IsWindow(target):
        return False
    api.SetForegroundWindow(target)
    time.sleep(0.1)
    return foreground_window() == target


def wait_for_modifiers(timeout: float = 2.0) -> bool:
    """Do not send Ctrl+C/V while the triggering Win/Shift/Alt keys are held."""
    api = _user32()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(api.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return True
        time.sleep(0.02)
    return False


def get_selected_text(timeout: float = 1.0, target=None, *, preserve_clipboard: bool = False) -> str:
    """Copy current selection via Ctrl+C and return clipboard text.

    The clipboard is cleared first and then polled for NEW content, so a copy
    that never lands (too fast, lost focus, nothing selected) returns ""
    instead of stale clipboard text. Restore the previous clipboard text on
    failure or when checking a selection before paste.
    """
    import pyperclip
    from pynput.keyboard import Controller, Key
    kb = Controller()
    if not wait_for_modifiers() or (target and foreground_window() != target):
        return ""
    try:
        old = pyperclip.paste()
    except Exception:
        return ""
    sentinel = f"__npuquilly_{uuid4().hex}__"
    try:
        pyperclip.copy(sentinel)
    except Exception:
        return ""
    text = sentinel
    captured = False
    try:
        if target and foreground_window() != target:
            return ""
        with kb.pressed(Key.ctrl):
            kb.press("c")
            time.sleep(0.05)
            kb.release("c")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                text = pyperclip.paste()
            except Exception:
                # The source application may still hold the clipboard open.
                pass
            else:
                if text != sentinel:
                    break
            time.sleep(0.05)
        captured = (text != sentinel and bool((text or "").strip())
                    and (not target or foreground_window() == target))
        return text if captured else ""
    finally:
        if preserve_clipboard or not captured:
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy(old)
            except Exception:
                pass


def replace_with(text: str, *, target, original: str):
    """Paste only after the current window and selection match the source."""
    import pyperclip
    from pynput.keyboard import Controller, Key
    kb = Controller()
    if not text.strip():
        raise ValueError("Refusing to paste an empty answer")
    if not wait_for_modifiers():
        raise PasteTargetChanged("Release the modifier keys before pasting.")
    if not target or foreground_window() != target:
        raise PasteTargetChanged("The source window lost focus.")
    try:
        selection = get_selected_text(target=target, preserve_clipboard=True)
    except Exception as exc:
        raise PasteTargetChanged("The original selection could not be verified.") from exc
    if not selection or selection != original:
        raise PasteTargetChanged("The original selection could not be verified.")
    if foreground_window() != target:
        raise PasteTargetChanged("The source window lost focus.")
    pyperclip.copy(text)
    time.sleep(0.05)
    if pyperclip.paste() != text:
        raise PasteTargetChanged("The clipboard changed before pasting.")
    if foreground_window() != target:
        raise PasteTargetChanged("The source window lost focus.")
    with kb.pressed(Key.ctrl):
        kb.press("v")
        kb.release("v")
