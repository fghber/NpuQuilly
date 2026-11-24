"""Settings dialog, including shortcut recording."""
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QProcess, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit

from app.hotkey_manager import parse_combo, validate_combo


class HotkeyEdit(QLineEdit):
    _MODIFIERS = (
        (Qt.KeyboardModifier.ControlModifier, "ctrl", "Ctrl"),
        (Qt.KeyboardModifier.AltModifier, "alt", "Alt"),
        (Qt.KeyboardModifier.MetaModifier, "cmd", "Win"),
        (Qt.KeyboardModifier.ShiftModifier, "shift", "Shift"),
    )
    _KEY_NAMES = {
        "backtab": "tab", "return": "enter", "del": "delete", "ins": "insert",
        "pgup": "page_up", "pgdown": "page_down", "print": "print_screen",
        "capslock": "caps_lock", "numlock": "num_lock", "scrolllock": "scroll_lock",
    }

    def __init__(self, combo: str):
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText("Disabled")
        self.setStyleSheet("QLineEdit:focus { border: 1px solid #aaa; }")
        self._set_combo((combo or "").strip())

    def _set_combo(self, combo: str):
        self.combo = combo
        labels = {name: label for _, name, label in self._MODIFIERS}
        parts = [part[1:-1] if part.startswith("<") and part.endswith(">") else part
                 for part in combo.split("+")]
        self.setText("+".join(labels.get(part.lower(), part.replace("_", " ").title())
                              for part in parts))

    def event(self, event):
        event_type = event.type()
        if event_type not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return super().event(event)

        key = event.key()
        modifiers = [name for flag, name, _ in self._MODIFIERS if event.modifiers() & flag]
        if (key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_AltGr,
                    Qt.Key.Key_Shift, Qt.Key.Key_Meta)
                or (not modifiers and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape,
                                              Qt.Key.Key_Return, Qt.Key.Key_Enter))
                or (modifiers == ["shift"] and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab))):
            return super().event(event)

        # Handle modified Tab and Qt shortcut keys before their default actions.
        event.accept()
        if event_type == QEvent.Type.ShortcutOverride or event.isAutoRepeat():
            return True
        if not modifiers and key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self._set_combo("")
            return True

        name = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText).lower()
        key_part = name if len(name) == 1 else f"<{self._KEY_NAMES.get(name, name)}>"
        parts = [f"<{modifier}>" for modifier in modifiers]
        combo = "+".join([*parts, key_part])
        if validate_combo(combo):
            self._set_combo(combo)
        else:
            QApplication.beep()
        return True


def show_settings(cfg, on_save: Callable, parent=None):
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                   QFormLayout, QLabel, QMessageBox, QPushButton, QTabWidget, QVBoxLayout,
                                   QWidget)
    from ui.styles import DARK
    dlg = QDialog(parent)
    dlg.setWindowTitle("NpuQuilly Settings")
    dlg.setStyleSheet(DARK)
    dlg.resize(440, 300)
    lay = QVBoxLayout(dlg)
    tabs = QTabWidget()
    lay.addWidget(tabs)

    api = QWidget()
    f1 = QFormLayout(api)
    e_url = QLineEdit(cfg.get("base_url"))
    e_key = QLineEdit(cfg.get("api_key") or "")
    e_key.setEchoMode(QLineEdit.Password)
    e_model = QLineEdit(cfg.get("model"))
    f1.addRow("Base URL", e_url)
    f1.addRow("API key", e_key)
    f1.addRow("Model", e_model)
    f1.addRow(QLabel("Selected text is sent to the configured API."))
    tabs.addTab(api, "API")

    dev = QWidget()
    f2 = QFormLayout(dev)
    c_dev = QComboBox()
    c_dev.addItems(["GPU", "NPU", "CPU"])
    c_dev.setCurrentText(cfg.get("device", "GPU"))
    f2.addRow("Device (server)", c_dev)
    f2.addRow(QLabel("Applies to the local OpenVINO server.\nNPU uses the grammar-battery model.\nFirst model compilation can take several minutes."))
    downloader = Path(__file__).resolve().parents[2] / "server" / "download_model.py"
    if downloader.is_file():
        download = QPushButton("Download model weights")
        download.setAutoDefault(False)
        download_status = QLabel()
        download_status.setWordWrap(True)
        download_status.setTextFormat(Qt.TextFormat.PlainText)
        f2.addRow(download)
        f2.addRow(download_status)
        process = QProcess(dlg)
        process.setStandardOutputFile(QProcess.nullDevice())
        process.setStandardErrorFile(QProcess.nullDevice())

        def start_download():
            model = "grammar-battery" if c_dev.currentText() == "NPU" else e_model.text().strip()
            if not model or model == "all":
                download_status.setText("Enter a single model alias on the API tab.")
                return
            download.setEnabled(False)
            download_status.setText(f"Downloading {model}. Closing Settings cancels the download.")
            process.start(sys.executable, [str(downloader), "--alias", model])

        def download_finished(exit_code, exit_status):
            download.setEnabled(True)
            if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
                download_status.setText("Model weights are ready. Click OK to apply your settings.")
            else:
                download_status.setText("Download failed. Check the model alias and connection, or rerun the download from PowerShell for details.")

        def download_error(error):
            if error == QProcess.ProcessError.FailedToStart:
                download.setEnabled(True)
                download_status.setText("Could not start the downloader. Rerun setup and try again.")

        def stop_download():
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)

        download.clicked.connect(start_download)
        process.finished.connect(download_finished)
        process.errorOccurred.connect(download_error)
        dlg.finished.connect(stop_download)
    tabs.addTab(dev, "Device")

    hk = QWidget()
    f3 = QFormLayout(hk)
    hk_edits = {}
    for k in ("popup", "repeat", "grammar", "rewrite"):
        e = HotkeyEdit((cfg.get("hotkeys") or {}).get(k, ""))
        hk_edits[k] = e
        f3.addRow(k.title(), e)
    f3.addRow(QLabel("Select a field and press a shortcut. Backspace clears it."))
    tabs.addTab(hk, "Hotkeys")

    beh = QWidget()
    f4 = QFormLayout(beh)
    c_paste = QCheckBox("Paste direct-hotkey results immediately (no preview)")
    c_paste.setChecked(bool(cfg.get("direct_paste", False)))
    f4.addRow(c_paste)
    tabs.addTab(beh, "Behavior")

    btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    lay.addWidget(btns)

    def save():
        hotkeys = {key: edit.combo for key, edit in hk_edits.items()}
        combos = [combo for combo in hotkeys.values() if combo]
        try:
            unique = {parse_combo(combo) for combo in combos}
        except ValueError:
            QMessageBox.warning(dlg, "Hotkeys", "Record a valid shortcut or clear its field.")
            return
        if len(unique) != len(combos):
            QMessageBox.warning(dlg, "Hotkeys", "Use valid, distinct hotkeys, or leave a hotkey blank to disable it.")
            return
        base_url, model = e_url.text().strip(), e_model.text().strip()
        if not base_url.startswith(("http://", "https://")) or not model:
            QMessageBox.warning(dlg, "API", "Enter an HTTP(S) base URL and a model name.")
            return
        patch = {"base_url": base_url, "model": model, "device": c_dev.currentText(),
                 "direct_paste": c_paste.isChecked(), "hotkeys": hotkeys}
        if e_key.text() != (cfg.get("api_key") or ""):
            patch["api_key"] = e_key.text()
        try:
            on_save(patch)
        except Exception as exc:
            QMessageBox.warning(dlg, "Could not apply settings", str(exc))
            return
        dlg.accept()

    btns.accepted.connect(save)
    btns.rejected.connect(dlg.reject)
    dlg.exec()
