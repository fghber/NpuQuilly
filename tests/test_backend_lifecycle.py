import sys
import time
import weakref
from types import SimpleNamespace

import httpx
import pytest

import main
from core.local_backend import LocalBackend
from server import server as api


@pytest.fixture
def isolated_backend(monkeypatch):
    events = []
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('No service')
    monkeypatch.setattr(httpx.Client, 'get', unavailable)

    class Server:
        started = False
        should_exit = False
        def __init__(self, config):
            pass
        def run(self):
            events.append('start')
            self.started = True
            while not self.should_exit:
                time.sleep(0.001)
            events.append('stop')

    import uvicorn
    monkeypatch.setattr(uvicorn, 'Server', Server)
    monkeypatch.setattr(api, 'unload_models', lambda: events.append('unload'))
    return events


def test_owned_server_stops_on_context_exit(isolated_backend):
    with LocalBackend('http://127.0.0.1:8000/v1') as backend:
        assert backend.owned
        assert backend._thread.daemon
        assert backend._thread.is_alive()
    assert not backend.owned
    assert isolated_backend == ['start', 'stop', 'unload']


def test_owned_server_stops_when_app_raises(isolated_backend):
    with pytest.raises(ValueError, match='GUI failed'):
        with LocalBackend('http://127.0.0.1:8000/v1'):
            raise ValueError('GUI failed')
    assert isolated_backend == ['start', 'stop', 'unload']


def test_closed_port_connect_timeout_still_starts_owned_server(isolated_backend, monkeypatch):
    def timeout(*args, **kwargs):
        raise httpx.ConnectTimeout('Closed port did not respond')
    monkeypatch.setattr(httpx.Client, 'get', timeout)
    with LocalBackend('http://127.0.0.1:8000/v1') as backend:
        assert backend.owned
    assert isolated_backend == ['start', 'stop', 'unload']


def test_device_change_unloads_owned_model(isolated_backend):
    with LocalBackend('http://127.0.0.1:8000/v1') as backend:
        backend.reconfigure(backend.base_url, unload=True)
        assert isolated_backend == ['start', 'unload']


def test_external_server_is_never_stopped(monkeypatch):
    monkeypatch.setattr(httpx.Client, 'get', lambda *a, **kw: httpx.Response(200))
    monkeypatch.setattr(api, 'unload_models', lambda: pytest.fail('External server must not be unloaded'))
    with LocalBackend('http://127.0.0.1:8000/v1') as backend:
        assert not backend.owned
        backend.unload()
    assert not backend.owned


@pytest.mark.parametrize('url', ['https://example.com/v1', 'http://localhost:1234/v1'])
def test_other_api_urls_remain_external(url, monkeypatch):
    monkeypatch.setattr(httpx.Client, 'get', lambda *a, **kw: pytest.fail('Must not probe another API'))
    with LocalBackend(url) as backend:
        assert not backend.owned


def test_changing_to_external_url_stops_owned_server(isolated_backend):
    with LocalBackend('http://127.0.0.1:8000/v1') as backend:
        backend.reconfigure('https://example.com/v1')
        assert not backend.owned
    assert isolated_backend == ['start', 'stop', 'unload']


def test_pipeline_switch_destroys_old_model_before_loading_new(tmp_path, monkeypatch):
    monkeypatch.setattr(api, '_pipes', {})
    monkeypatch.setattr(api, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(api.Path, 'is_file', lambda self: True)
    class Pipeline:
        pass
    old = Pipeline()
    old_ref = weakref.ref(old)
    api._pipes[('grammar-battery', 'NPU')] = old
    del old

    def create(*args, **kwargs):
        assert old_ref() is None, 'Previous pipeline must be destroyed before loading the new one'
        return Pipeline()

    monkeypatch.setitem(sys.modules, 'openvino', SimpleNamespace(
        Core=lambda: SimpleNamespace(available_devices=['GPU', 'NPU'])))
    monkeypatch.setitem(sys.modules, 'openvino_genai', SimpleNamespace(LLMPipeline=create))
    pipe = api.get_pipe('grammar-fast', 'GPU')
    assert list(api._pipes) == [('grammar-fast', 'GPU')]
    assert api.get_pipe('grammar-fast', 'GPU') is pipe
    api.unload_models()
    assert api._pipes == {}


def test_main_closes_backend_after_gui_exit(monkeypatch):
    from app import application
    from core import local_backend, single_instance
    events = []
    class Backend:
        def __init__(self, url):
            assert url == 'http://127.0.0.1:8000/v1'
        def __enter__(self):
            events.append('backend-start')
            return self
        def __exit__(self, *args):
            events.append('backend-stop')
    class App:
        cfg = SimpleNamespace(get=lambda key: 'http://127.0.0.1:8000/v1')
        def run_gui(self):
            assert isinstance(self.backend, Backend)
            events.append('gui')
            return 0
    monkeypatch.setattr(main, '_crash_log_setup', lambda: None)
    monkeypatch.setattr(single_instance, 'acquire', lambda: True)
    monkeypatch.setattr(single_instance, 'release', lambda: events.append('unlock'))
    monkeypatch.setattr(application, 'NpuQuillyApp', App)
    monkeypatch.setattr(local_backend, 'LocalBackend', Backend)
    assert main.main([]) == 0
    assert events == ['backend-start', 'gui', 'backend-stop', 'unlock']
