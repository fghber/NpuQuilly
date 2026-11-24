import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server import server as backend


class Tokenizer:
    def apply_chat_template(self, messages, add_generation_prompt):
        assert add_generation_prompt
        return 'MODEL-TEMPLATE:' + messages[-1]['content']

    def encode(self, text, add_special_tokens=False):
        return SimpleNamespace(input_ids=SimpleNamespace(shape=(1, len(text.split()))))


class Pipeline:
    def get_tokenizer(self):
        return Tokenizer()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(backend, 'DEVICE_OVERRIDE', '')
    monkeypatch.setattr(backend, 'get_pipe', lambda model, device: Pipeline())
    monkeypatch.setattr(backend, 'generate_text', lambda *args: ('Fixed.', 2))
    with TestClient(backend.app) as c:
        yield c


def request(**overrides):
    return {'model': 'grammar-fast', 'messages': [{'role': 'user', 'content': 'Fix me.'}], **overrides}


def test_success_uses_template_and_reports_device(client, monkeypatch):
    def generate(pipe, prompt, temp, budget):
        assert prompt == 'MODEL-TEMPLATE:Fix me.'
        assert budget == 256
        return 'Fixed.', 2
    monkeypatch.setattr(backend, 'generate_text', generate)
    res = client.post('/v1/chat/completions', json=request(device='CPU', max_tokens=256))
    assert res.status_code == 200
    assert res.json()['device'] == 'CPU'
    assert res.json()['choices'][0]['message']['content'] == 'Fixed.'


@pytest.mark.parametrize('overrides', [
    {'messages': []}, {'messages': [{'role': 'user', 'content': None}]},
    {'messages': 'oops'}, {'temperature': -1}, {'temperature': 'nan'},
    {'max_tokens': -1}, {'max_tokens': 100000}, {'max_tokens': '20'}, {'device': 'TPU'},
])
def test_invalid_requests_return_422(client, overrides):
    assert client.post('/v1/chat/completions', json=request(**overrides)).status_code == 422


def test_streaming_explicitly_rejected(client):
    assert client.post('/v1/chat/completions', json=request(stream=True)).status_code == 400


def test_unknown_model_is_404(client):
    assert client.post('/v1/chat/completions', json=request(model='missing')).status_code == 404


def test_wrong_npu_export_is_rejected(client):
    assert client.post('/v1/chat/completions', json=request(device='NPU')).status_code == 400


def test_long_npu_prompt_is_rejected_before_generation(client, monkeypatch):
    monkeypatch.setattr(backend, 'generate_text', lambda *a: pytest.fail('Must not generate'))
    res = client.post('/v1/chat/completions', json=request(
        model='grammar-battery', messages=[{'role': 'user', 'content': 'word ' * 1100}]))
    assert res.status_code == 400
    assert '1024' in res.json()['detail']


def test_npu_response_is_bounded_by_remaining_context(client, monkeypatch):
    def generate(pipe, prompt, temp, budget):
        assert budget == 380  # 1024 + 256 - 900 prompt tokens
        return 'partial', budget
    monkeypatch.setattr(backend, 'generate_text', generate)
    res = client.post('/v1/chat/completions', json=request(
        model='grammar-battery', max_tokens=4096,
        messages=[{'role': 'user', 'content': 'word ' * 900}]))
    assert res.status_code == 200
    assert res.json()['choices'][0]['finish_reason'] == 'length'


def test_failed_inference_is_not_retried(client, monkeypatch):
    calls = []
    def generate(*args):
        calls.append(1)
        raise RuntimeError('Device lost')
    monkeypatch.setattr(backend, 'generate_text', generate)
    assert client.post('/v1/chat/completions', json=request()).status_code == 503
    assert calls == [1]


def test_requests_never_generate_concurrently(client, monkeypatch):
    active = 0
    peak = 0
    guard = threading.Lock()
    def generate(*args):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with guard:
            active -= 1
        return 'Fixed.', 2
    monkeypatch.setattr(backend, 'generate_text', generate)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post('/v1/chat/completions', json=request()), range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert peak == 1


@pytest.mark.parametrize('temperature', [0.0, 0.7])
def test_generation_config_has_one_template_and_bound(temperature):
    class FakePipe:
        def generate(self, prompt, cfg):
            assert prompt == ['prompt']
            assert cfg.max_new_tokens == 32
            assert cfg.do_sample is (temperature > 0)
            assert cfg.apply_chat_template is False
            return SimpleNamespace(texts=['Fixed.'], perf_metrics=SimpleNamespace(
                get_num_generated_tokens=lambda: 2))
    assert backend.generate_text(FakePipe(), 'prompt', temperature, 32) == ('Fixed.', 2)


def test_generation_counts_tokens_for_results_without_metrics():
    class FakePipe(Pipeline):
        def generate(self, prompt, cfg):
            return 'Fixed text.'

    assert backend.generate_text(FakePipe(), 'prompt', 0.0, 32) == ('Fixed text.', 2)


def test_empty_grammar_is_rejected(client):
    assert client.post('/grammar', json={'text': '  '}).status_code == 400
