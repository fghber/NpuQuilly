"""Windows tray writing helper: capture selection, run local LLM, preview/paste."""
import time
from urllib.parse import urlparse

from core.ai_provider import AIProvider
from core.chatml_parser import build_messages
from core.config_manager import ConfigManager
from core.crypto_manager import protect, unprotect
from core.device_manager import normalize, should_warn_npu
from core.output_cleaner import clean_output
from core.prompt_manager import PromptManager


class NpuQuillyApp:
    ACTION_MAP = {"grammar": "grammar_check", "grammar_check": "grammar_check",
                  "rewrite": "rewrite", "summarize": "summarize", "custom": "custom"}

    def __init__(self):
        self.cfg = ConfigManager()
        self.prompts = PromptManager()
        self.provider = AIProvider()
        self._wire_provider()
        self.last_action = self.cfg.get("last_action", "grammar_check")
        self.last_instruction = ""

    def _wire_provider(self):
        key = self.cfg.get("api_key", "dummy")
        if isinstance(key, str) and key.startswith(("dpapi:", "b64:")):
            key = unprotect(key)
        self.provider.configure(self.cfg.get("base_url"), key, self.cfg.get("model"))

    def save_settings(self, patch: dict):
        patch = dict(patch)
        unload = any(key in patch and patch[key] != self.cfg.get(key)
                     for key in ("device", "model", "action_models"))
        if patch.get("api_key") and patch["api_key"] != "dummy":
            patch["api_key"] = protect(patch["api_key"])
        self.cfg.data.update(patch)
        self.cfg.save()
        self._wire_provider()
        if getattr(self, "backend", None) is not None:
            self.backend.reconfigure(self.cfg.get("base_url"), unload=unload)

    def is_local(self) -> bool:
        return urlparse(self.cfg.get("base_url", "")).hostname in ("127.0.0.1", "localhost", "::1")

    def resolve_model(self, action: str) -> str:
        # NPU needs the symmetric INT4 export, including for rewrite/custom.
        if self.is_local() and normalize(self.cfg.get("device")) == "NPU":
            return "grammar-battery"
        routed = (self.cfg.get("action_models", {}) or {}).get(action)
        return routed or self.cfg.get("model")

    def run_action(self, text: str, action: str, instruction: str = "") -> tuple[str, float]:
        if not text.strip():
            raise ValueError("Select some text first")
        if len(text) > 65536:
            raise ValueError("Selection too long; select a shorter passage")
        action = self.ACTION_MAP.get(action, "grammar_check")
        if action == "custom" and not instruction.strip():
            raise ValueError("Enter a custom instruction")
        model = self.resolve_model(action)
        device = normalize(self.cfg.get("device"))
        local = self.is_local()
        prompt = self.prompts.get(action)
        template = prompt["template"]
        if local and action == "grammar_check" and (device, model) in (
                ("GPU", "grammar-fast"), ("NPU", "grammar-battery")):
            template = prompt.get("local_phi_template", template)
        messages = build_messages(template, text, instruction)
        warn = should_warn_npu(device, len(text))
        if warn:
            print(f"[npuquilly] {warn}")
        print(f"[npuquilly] action={action} model={model} device={device}")
        t0 = time.monotonic()
        # UTF-8 bytes provide a generous bound for spelling corrections, including
        # languages without spaces. The provider rejects token-limited responses.
        budget = min(4096, max(256, len(text.encode("utf-8")) + 128))
        out = self.provider.complete(messages, temperature=self.prompts.temperature(action),
                                     max_tokens=budget, model=model,
                                     extra={"device": device} if local else None)
        result = clean_output(out, original=text)
        if not result.strip():
            raise RuntimeError("The model returned no usable text; the selection was preserved")
        # Clean model wrapping without removing the selection's edge whitespace.
        leading = text[:len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()):]
        result = leading + result.strip() + trailing
        self.last_action = action
        if action == "custom":
            self.last_instruction = instruction
        self.cfg.set("last_action", action)
        return result, time.monotonic() - t0

    def run_gui(self):
        import sys
        from PySide6.QtCore import QObject, QThread, Signal, Slot
        from PySide6.QtWidgets import QApplication
        from app.hotkey_manager import HotkeyManager
        from app.text_processor import (PasteTargetChanged, foreground_window, get_selected_text,
                                        replace_with, restore_window)
        from app.tray_manager import TrayManager
        from ui.popup_window import show_request, show_result
        from ui.settings_window import show_settings

        app = self
        qt = QApplication(sys.argv)
        qt.setQuitOnLastWindowClosed(False)

        class Bridge(QObject):
            requested = Signal(str)
            captured = Signal(str, str, object)  # action, selection, source HWND
            completed = Signal(str, str, float, bool, object)
            failed = Signal(str)

        bridge = Bridge()
        workers = set()
        state = {"busy": False, "quitting": False, "settings": False}

        class CaptureWorker(QThread):
            def __init__(self, action, target):
                super().__init__()
                self.action, self.target = action, target

            def run(self):
                try:
                    text = get_selected_text(target=self.target)
                    bridge.captured.emit(self.action, text, self.target)
                except Exception as e:
                    bridge.failed.emit(f"Selection capture failed: {e}")

        class GenerateWorker(QThread):
            def __init__(self, text, action, instruction, direct, target):
                super().__init__()
                self.text, self.action, self.instruction = text, action, instruction
                self.direct, self.target = direct, target

            def run(self):
                try:
                    result, dt = app.run_action(self.text, self.action, self.instruction)
                    bridge.completed.emit(self.text, result, dt, self.direct, self.target)
                except Exception as e:
                    bridge.failed.emit(f"{type(e).__name__}: {e}")

        def notify(message):
            print(f"[npuquilly] {message}")
            tray.tray.showMessage("NpuQuilly", message)

        def start_worker(worker):
            workers.add(worker)
            def cleanup():
                workers.discard(worker)
                worker.deleteLater()
                if state["quitting"] and not workers:
                    qt.quit()
            worker.finished.connect(cleanup)
            worker.start()

        def quit_app():
            state["quitting"] = True
            hk.stop()
            if workers:
                notify("Finishing the current request before exiting. Its result will not be pasted.")
            else:
                qt.quit()

        def save_settings(patch):
            app.save_settings(patch)
            hk.stop()
            hk.hotkeys = app.cfg.get("hotkeys")
            hk.start()

        def settings():
            if state["busy"]:
                notify("Wait for the current request before changing settings.")
                return
            state["settings"] = True
            try:
                show_settings(app.cfg.data, save_settings)
            finally:
                state["settings"] = False

        tray = TrayManager(qt, on_settings=settings, on_quit=quit_app)
        tray.show()

        @Slot(str)
        def on_requested(action):
            if state["quitting"] or state["settings"] or tray.paused:
                return
            if state["busy"]:
                notify("A request is already in progress.")
                return
            state["busy"] = True
            # Capture BEFORE opening a Qt dialog, while the source still has focus.
            start_worker(CaptureWorker(action, foreground_window()))

        @Slot(str, str, object)
        def on_captured(action, text, target):
            if state["quitting"]:
                return
            if not text.strip():
                state["busy"] = False
                notify("No text captured. Select text in the source app and try again.")
                return
            direct = action != "__popup__"
            instruction = ""
            if action == "__popup__":
                picked = show_request()
                if not picked or state["quitting"]:
                    state["busy"] = False
                    return
                action, instruction = picked
            elif action == "__repeat__":
                action, instruction = app.last_action, app.last_instruction
            # Repeating a summary still requires reviewing it before pasting.
            start_worker(GenerateWorker(text, action, instruction, direct and action != "summarize", target))

        @Slot(str, str, float, bool, object)
        def on_completed(original, result, dt, direct, target):
            if state["quitting"]:
                return
            def paste(value, refocus=True):
                try:
                    if refocus and not restore_window(target):
                        raise PasteTargetChanged("Could not focus the source window.")
                    replace_with(value, target=target, original=original)
                except PasteTargetChanged as exc:
                    show_result(original, value, dt, on_accept=None,
                                notice=f"{exc} Copy the result to paste it manually.")
            try:
                if direct and app.cfg.get("direct_paste", False) and foreground_window() == target:
                    paste(result, refocus=False)
                else:
                    show_result(original, result, dt, on_accept=paste)
            except Exception as e:
                notify(str(e))
            finally:
                state["busy"] = False

        @Slot(str)
        def on_failed(message):
            state["busy"] = False
            if not state["quitting"]:
                # A provider error can echo the submitted text in its detail.
                tray.tray.showMessage("NpuQuilly", message)

        bridge.requested.connect(on_requested)
        bridge.captured.connect(on_captured)
        bridge.completed.connect(on_completed)
        bridge.failed.connect(on_failed)
        # Listener callbacks only signal the GUI thread.
        hk = HotkeyManager(self.cfg.get("hotkeys"),
                           on_popup=lambda: bridge.requested.emit("__popup__"),
                           on_direct=lambda a: bridge.requested.emit(a))
        hk.start()
        print(f"NpuQuilly running | model={self.cfg.get('model')} "
              f"device={normalize(self.cfg.get('device'))}")
        try:
            return qt.exec()
        finally:
            hk.stop()
            # Normal quit waits asynchronously above; never destroy a live QThread.
            for worker in list(workers):
                worker.wait()
            self.provider.close()
