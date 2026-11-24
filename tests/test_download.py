import sys
from types import SimpleNamespace

import pytest

from server import download_model


def test_partial_download_is_resumed(tmp_path, monkeypatch):
    (tmp_path / 'config.json').write_text('{}')
    calls = []
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        snapshot_download=lambda **kw: calls.append(kw)))
    assert download_model.download('example/model', str(tmp_path)) == tmp_path
    assert calls == [{'repo_id': 'example/model', 'local_dir': str(tmp_path)}]


def test_unknown_download_alias_returns_error(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['download_model.py', '--alias', 'typo'])
    with pytest.raises(SystemExit) as exc:
        download_model.main()
    assert exc.value.code == 2
