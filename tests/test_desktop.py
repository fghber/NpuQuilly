import sys
from contextlib import nullcontext
from itertools import count
from types import SimpleNamespace

import pytest

from app import text_processor


def test_focus_change_prevents_paste(monkeypatch):
    copied = []
    monkeypatch.setitem(sys.modules, 'pyperclip', SimpleNamespace(copy=copied.append))
    monkeypatch.setattr(text_processor, 'wait_for_modifiers', lambda: True)
    monkeypatch.setattr(text_processor, 'foreground_window', lambda: 999)
    with pytest.raises(RuntimeError, match='lost focus'):
        text_processor.replace_with('Do not paste this.', target=123, original='Original text.')
    assert copied == []


def test_capture_waits_for_hotkey_release(monkeypatch):
    monkeypatch.setattr(text_processor, 'wait_for_modifiers', lambda: False)
    # Neither the clipboard nor the active selection should be touched.
    monkeypatch.setitem(sys.modules, 'pyperclip', SimpleNamespace(
        copy=lambda t: pytest.fail('Clipboard must not change')))
    assert text_processor.get_selected_text(target=123) == ''


@pytest.mark.parametrize('pending_reads', [(), ('sentinel', 'busy')])
def test_capture_polls_immediately_and_retries_pending_copies(monkeypatch, pending_reads):
    from pynput import keyboard

    clipboard = 'Previous clipboard'
    released = False
    pending = iter(pending_reads)
    sleeps = []
    def copy(value):
        nonlocal clipboard
        clipboard = value

    def release(key):
        nonlocal released
        assert key == 'c'
        released = True

    def paste():
        if not released:
            return clipboard
        state = next(pending, 'ready')
        if state == 'busy':
            raise RuntimeError('clipboard is busy')
        return clipboard if state == 'sentinel' else 'Selected text'

    timer = count(step=0.01)
    monkeypatch.setattr(text_processor, 'time', SimpleNamespace(sleep=sleeps.append, monotonic=lambda: next(timer)))
    monkeypatch.setattr(text_processor, 'wait_for_modifiers', lambda: True)
    monkeypatch.setattr(text_processor, 'foreground_window', lambda: 123)
    monkeypatch.setitem(sys.modules, 'pyperclip', SimpleNamespace(paste=paste, copy=copy))
    monkeypatch.setattr(keyboard, 'Controller', lambda: SimpleNamespace(
        pressed=lambda _: nullcontext(), press=lambda _: None, release=release))
    assert text_processor.get_selected_text(target=123) == 'Selected text'
    assert sleeps == [0.05] * (1 + len(pending_reads))  # key hold, then only pending polls


@pytest.mark.parametrize('selection,clipboard_changes,pastes', [
    (' Original text.\n', False, True),
    ('Original text.', False, False),
    ('Some other text.', False, False),
    (None, False, False),
    (' Original text.\n', True, False),
])
def test_paste_verifies_current_selection_and_clipboard(monkeypatch, selection, clipboard_changes, pastes):
    from pynput import keyboard

    original, result = ' Original text.\n', 'Updated text.'
    clipboard = 'Previous clipboard text.'
    sent = []

    def copy(value):
        nonlocal clipboard
        clipboard = 'A newer copy.' if clipboard_changes and value == result else value

    def press(key):
        sent.append(key)
        if key == 'c' and selection is not None:
            copy(selection)

    timer = count(step=0.1)
    monkeypatch.setattr(text_processor, 'time', SimpleNamespace(sleep=lambda _: None, monotonic=lambda: next(timer)))
    monkeypatch.setattr(text_processor, 'wait_for_modifiers', lambda: True)
    monkeypatch.setattr(text_processor, 'foreground_window', lambda: 123)
    monkeypatch.setitem(sys.modules, 'pyperclip', SimpleNamespace(paste=lambda: clipboard, copy=copy))
    monkeypatch.setattr(keyboard, 'Controller', lambda: SimpleNamespace(
        pressed=lambda _: nullcontext(), press=press, release=lambda _: None))

    if pastes:
        text_processor.replace_with(result, target=123, original=original)
        assert sent == ['c', 'v'] and clipboard == result
    else:
        message = 'clipboard changed' if clipboard_changes else 'original selection'
        with pytest.raises(text_processor.PasteTargetChanged, match=message):
            text_processor.replace_with(result, target=123, original=original)
        assert sent == ['c']
        assert clipboard == ('A newer copy.' if clipboard_changes else 'Previous clipboard text.')


def test_menu_to_preview_to_source_paste(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from app.application import NpuQuillyApp
    from app import hotkey_manager, tray_manager
    from core.config_manager import ConfigManager
    from core.prompt_manager import PromptManager
    from ui import popup_window

    events = []
    errors = []
    copied = []
    hotkeys = None
    passage = 'The team met on Monday. The decision was to delay the launch.'
    result = 'The team delayed the launch.'
    original_request = popup_window.show_request
    original_result = popup_window.show_result

    def click_button(prefix):
        dialog = QApplication.activeModalWidget()
        assert dialog is not None
        for button in dialog.findChildren(QPushButton):
            if button.text().startswith(prefix):
                button.click()
                return
        raise AssertionError(f'Button not found: {prefix}')

    def menu():
        assert events == ['captured']
        events.append('menu')
        QTimer.singleShot(0, lambda: click_button('&Summarize'))
        return original_request()

    def preview(*args, **kwargs):
        if kwargs['on_accept'] is None:
            events.append('copy-only preview')
            QTimer.singleShot(0, copy_and_dismiss)
        else:
            events.append('preview')
            QTimer.singleShot(0, lambda: click_button('Accept'))
        return original_result(*args, **kwargs)

    def copy_and_dismiss():
        dlg = QApplication.activeModalWidget()
        assert any('selection changed' in label.text() for label in dlg.findChildren(QLabel))
        assert {button.text() for button in dlg.findChildren(QPushButton)} == {'Copy', 'Dismiss'}
        click_button('Copy')
        click_button('Dismiss')
        QTimer.singleShot(0, QApplication.instance().quit)

    def capture(**kwargs):
        assert kwargs['target'] == 123
        events.append('captured')
        return passage

    def paste(text, *, target, original):
        assert text == result and target == 123 and original == passage
        assert QApplication.activeModalWidget() is None
        if events.count('captured') == 3:
            raise text_processor.PasteTargetChanged('The selection changed.')
        events.append('pasted')
        if events.count('pasted') == 1:
            QTimer.singleShot(0, lambda: hotkeys.on_direct('__repeat__'))
        else:
            QTimer.singleShot(0, lambda: hotkeys.on_direct('grammar_check'))

    class Hotkeys:
        def __init__(self, hotkeys, on_popup, on_direct):
            self.on_popup = on_popup
            self.on_direct = on_direct
        def start(self):
            nonlocal hotkeys
            hotkeys = self
            QTimer.singleShot(0, self.on_popup)
        def stop(self):
            pass

    class Tray:
        paused = False
        def __init__(self, *args, **kwargs):
            self.tray = SimpleNamespace(showMessage=lambda title, msg: errors.append(msg))
        def show(self):
            # Fail fast instead of leaving a broken UI test running indefinitely.
            QTimer.singleShot(5000, QApplication.instance().quit)

    monkeypatch.setattr(hotkey_manager, 'HotkeyManager', Hotkeys)
    monkeypatch.setattr(tray_manager, 'TrayManager', Tray)
    monkeypatch.setitem(sys.modules, 'pyperclip', SimpleNamespace(copy=copied.append))
    monkeypatch.setattr(text_processor, 'foreground_window', lambda: 123)
    monkeypatch.setattr(text_processor, 'get_selected_text', capture)
    monkeypatch.setattr(text_processor, 'restore_window', lambda target: target == 123)
    monkeypatch.setattr(text_processor, 'replace_with', paste)
    monkeypatch.setattr(popup_window, 'show_request', menu)
    monkeypatch.setattr(popup_window, 'show_result', preview)
    app = NpuQuillyApp.__new__(NpuQuillyApp)
    app.cfg = ConfigManager(tmp_path / 'config.json')
    app.cfg.set('direct_paste', True)
    app.prompts = PromptManager()
    app.last_action, app.last_instruction = 'grammar_check', ''
    app.provider = SimpleNamespace(complete=lambda *a, **kw: result, close=lambda: None)
    assert app.run_gui() == 0
    assert errors == []
    assert events == ['captured', 'menu', 'preview', 'pasted', 'captured', 'preview', 'pasted',
                      'captured', 'copy-only preview']
    assert copied == [result]


def test_hotkey_settings_record_clear_and_reject_duplicates(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QTabWidget
    from core.config_manager import DEFAULTS
    from ui.settings_window import HotkeyEdit, show_settings

    qt = QApplication.instance() or QApplication([])
    cfg = {**DEFAULTS, 'api_key': 'b64:c2F2ZWQ=',
           'hotkeys': {**DEFAULTS['hotkeys'], 'grammar': '<shift>+<ctrl>+G'}}
    warnings, saved, observed = [], [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda _, title, text: warnings.append(title))

    def interact():
        dlg = qt.activeModalWidget()
        tabs = dlg.findChild(QTabWidget)
        tabs.setCurrentIndex(2)
        popup, repeat, grammar, rewrite = tabs.currentWidget().findChildren(HotkeyEdit)
        ok = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        rewrite.setFocus()
        QTest.keyClick(rewrite, Qt.Key.Key_G, modifiers)
        observed.append(rewrite.text())
        ok.click()
        observed.append(dlg.isVisible())
        QTest.keyClick(rewrite, Qt.Key.Key_F9, Qt.KeyboardModifier.AltModifier)
        repeat.setFocus()
        QTest.keyClick(repeat, Qt.Key.Key_Backspace)
        ok.click()

    QTimer.singleShot(0, interact)
    show_settings(cfg, saved.append)
    assert observed == ['Ctrl+Shift+G', True]
    assert warnings == ['Hotkeys']
    assert len(saved) == 1 and 'api_key' not in saved[0]
    assert saved[0]['hotkeys'] == {'popup': '<cmd>+<shift>+q', 'repeat': '',
                                  'grammar': '<shift>+<ctrl>+G', 'rewrite': '<alt>+<f9>'}


def test_settings_shows_save_failure_and_keeps_dialog_open(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QMessageBox
    from core.config_manager import DEFAULTS
    from ui.settings_window import show_settings

    qt = QApplication.instance() or QApplication([])
    warnings, visible = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda _, title, text: warnings.append(text))

    def fail_save(patch):
        if patch['api_key'] == 'replacement':
            raise RuntimeError('Windows could not encrypt the API key. The saved key was kept.')

    def interact():
        dlg = qt.activeModalWidget()
        key = next(edit for edit in dlg.findChildren(QLineEdit) if edit.echoMode() == QLineEdit.Password)
        key.setText('replacement')
        buttons = dlg.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        visible.append(dlg.isVisible())
        buttons.button(QDialogButtonBox.StandardButton.Cancel).click()

    QTimer.singleShot(0, interact)
    show_settings(DEFAULTS, fail_save)
    assert visible == [True]
    assert warnings == ['Windows could not encrypt the API key. The saved key was kept.']


@pytest.mark.parametrize('device,alias', [('GPU', 'rewrite-alt'), ('NPU', 'grammar-battery')])
def test_settings_downloads_one_model_for_selected_device(tmp_path, monkeypatch, device, alias):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QTabWidget
    from core.config_manager import DEFAULTS
    from ui import settings_window

    downloader = tmp_path / 'server' / 'download_model.py'
    downloader.parent.mkdir()
    downloader.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(__file__).with_suffix('.args').write_text(' '.join(sys.argv[1:]))\n",
        encoding='utf-8',
    )
    monkeypatch.setattr(settings_window, '__file__',
                        str(tmp_path / 'NpuQuilly' / 'ui' / 'settings_window.py'))
    qt = QApplication.instance() or QApplication([])
    saved, statuses = [], []

    def interact():
        dlg = qt.activeModalWidget()
        tabs = dlg.findChild(QTabWidget)
        tabs.setCurrentIndex(1)
        page = tabs.currentWidget()
        page.findChild(QComboBox).setCurrentText(device)
        download = page.findChild(QPushButton)
        download.click()
        for _ in range(100):
            if download.isEnabled():
                break
            QTest.qWait(50)
        statuses.extend(label.text() for label in page.findChildren(QLabel))
        dlg.reject()

    QTimer.singleShot(0, interact)
    settings_window.show_settings({**DEFAULTS, 'model': 'rewrite-alt'}, saved.append)
    assert downloader.with_suffix('.args').read_text(encoding='utf-8') == f'--alias {alias}'
    assert 'Model weights are ready. Click OK to apply your settings.' in statuses
    assert saved == []
