"""NpuQuilly entry point."""
import sys


def _crash_log_setup():
    """faulthandler to stderr + uncaught exceptions to %APPDATA%/NpuQuilly/npuquilly.log."""
    import datetime
    import faulthandler
    import traceback
    try:
        from core.config_manager import config_path
        log = config_path().parent / "npuquilly.log"
    except Exception:
        return None
    # pythonw/PyInstaller --windowed have no stderr. Keep a real stream alive
    # for native fault reports and the same progress/errors as console launches.
    if sys.stdout is None:
        sys.stdout = open(log, "a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=sys.stderr)

    def hook(t, v, tb):
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} uncaught ===\n")
                traceback.print_exception(t, v, tb, file=f)
        except Exception:
            pass
    sys.excepthook = hook
    return log


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check-hotkeys" in argv:
        from core.config_manager import ConfigManager
        cfg = ConfigManager()
        try:
            from app.hotkey_manager import validate_combo
        except ImportError:
            print("pynput not installed; cannot validate (pip install -r requirements.txt)")
            return 2
        ok = True
        for name, combo in (cfg.get("hotkeys") or {}).items():
            if combo in ("", None):
                print(f"  {name:8} {'':25} DISABLED")
                continue
            try:
                good = validate_combo(combo)
            except ImportError:
                print("pynput not installed; cannot validate (pip install -r requirements.txt)")
                return 2
            print(f"  {name:8} {combo:25} {'OK' if good else 'INVALID'}")
            ok = ok and good
        return 0 if ok else 1
    if "--smoke" in argv:
        # Import everything without touching Qt/drivers/network.
        import core.chatml_parser as p
        import core.prompt_manager as pm
        import core.config_manager as cm
        import core.device_manager as dm
        import core.ai_provider as ap
        msgs = p.parse_messages(p.render("<|im_start|>user\n{{text}}<|im_end|>", text="hi"))
        assert msgs and msgs[0]["content"] == "hi", msgs
        assert set(pm.PromptManager().prompts) == set(pm.ACTIONS)
        assert dm.normalize("npu") == "NPU"
        assert dm.should_warn_npu("NPU", 99999) is not None
        assert dm.should_warn_npu("GPU", 99999) is None
        # v1 -> v2 hotkey migration (Ctrl+Space is IME/VS Code territory)
        import json as _json
        import tempfile as _tf
        from pathlib import Path as _Path
        with _tf.TemporaryDirectory() as td:
            p = _Path(td) / "config.json"
            p.write_text(_json.dumps({"hotkeys": {"popup": "<ctrl>+<space>"}}),
                         encoding="utf-8")
            migrated = cm.ConfigManager(path=p)
            assert migrated.get("hotkeys")["popup"] == cm.DEFAULTS["hotkeys"]["popup"], \
                migrated.get("hotkeys")
            assert migrated.get("config_version") == cm.CONFIG_VERSION
        # LAST: DPAPI round-trip (native code — must not segfault; see settings-close crash)
        from core.crypto_manager import protect as _p, unprotect as _u
        assert _u(_p("smoke-key-123")) == "smoke-key-123"
        # Output cleaner: template leakage stripped, content preserved
        from core.output_cleaner import clean_output as _co
        assert _co("She doesn't like apples.</text>") == "She doesn't like apples."
        assert _co("<text>Hi.</text>") == "Hi."
        assert _co("```\nFixed text.\n```") == "Fixed text."
        assert _co("Here is the corrected text:\nFixed.") == "Fixed."
        assert _co("Unchanged sentence.") == "Unchanged sentence."
        assert _co("") == ""
        import ui.popup_window as _pw
        assert callable(_pw.show_request) and callable(_pw.show_result)
        assert cm.DEFAULTS.get("direct_paste") is False
        assert cm.DEFAULTS.get("action_models") == {}
        print("smoke OK")
        return 0
    from core.single_instance import acquire, lock_pid
    if not acquire():
        print(f"NpuQuilly is already running (tray, pid {lock_pid()}). "
              f"Quit via tray, or: taskkill /PID {lock_pid()} /F")
        return 0
    log = _crash_log_setup()
    if log is not None:
        print(f"[npuquilly] crash log: {log}")
    try:
        from app.application import NpuQuillyApp
        from core.local_backend import LocalBackend
        app = NpuQuillyApp()
        with LocalBackend(app.cfg.get("base_url")) as backend:
            app.backend = backend
            return app.run_gui()
    finally:
        from core.single_instance import release
        release()


if __name__ == "__main__":
    raise SystemExit(main())
