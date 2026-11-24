import sys

import main
from core.config_manager import ConfigManager, DEFAULTS


def test_hotkey_check_reports_disabled_shortcuts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    ConfigManager().set('hotkeys', {**DEFAULTS['hotkeys'], 'repeat': ''})
    assert main.main(['--check-hotkeys']) == 0
    assert any('repeat' in line and 'DISABLED' in line for line in capsys.readouterr().out.splitlines())


def test_windowless_launch_has_streams_for_fault_and_progress_logs(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr(sys, 'excepthook', sys.excepthook)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    streams = []
    try:
        log = main._crash_log_setup()
        streams = [sys.stdout, sys.stderr]
        assert all(stream is not None for stream in streams)
        print('Windowless startup works.', flush=True)
        assert 'Windowless startup works.' in log.read_text(encoding='utf-8')
    finally:
        monkeypatch.setattr(sys, 'stdout', old_stdout)
        monkeypatch.setattr(sys, 'stderr', old_stderr)
        import faulthandler
        faulthandler.enable(file=old_stderr)
        for stream in streams:
            stream.close()
