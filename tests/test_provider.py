import httpx
import pytest

from core.ai_provider import AIProvider


def provider(response):
    obj = AIProvider()
    obj.configure('http://127.0.0.1:8000/v1', 'dummy', 'grammar-fast')
    obj._client.close()
    obj._client = httpx.Client(base_url=obj.base_url, transport=httpx.MockTransport(response))
    return obj


def test_provider_keeps_v1_path_and_sends_selected_model():
    import json
    def respond(req):
        assert req.url.path == '/v1/chat/completions'
        assert json.loads(req.content)['model'] == 'grammar-battery'
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Fixed.'}, 'finish_reason': 'stop'}]})
    obj = provider(respond)
    try:
        assert obj.complete([{'role': 'user', 'content': 'Fix.'}], model='grammar-battery') == 'Fixed.'
    finally:
        obj.close()


@pytest.mark.parametrize('choice,match', [
    ({'message': {'content': 'Incomplete'}, 'finish_reason': 'length'}, 'truncated'),
    ({'message': {'content': ''}}, 'empty'),
    ({'message': {'content': None}}, 'empty'),
    ({}, 'Bad API response'),
])
def test_provider_rejects_unusable_answers(choice, match):
    obj = provider(lambda req: httpx.Response(200, json={'choices': [choice]}))
    try:
        with pytest.raises(RuntimeError, match=match):
            obj.complete([{'role': 'user', 'content': 'Fix.'}])
    finally:
        obj.close()


def test_server_error_explains_how_to_fix_request():
    obj = provider(lambda req: httpx.Response(400, json={'detail': 'NPU prompt exceeds 1024 tokens; use GPU.'}))
    try:
        with pytest.raises(RuntimeError, match='1024 tokens; use GPU'):
            obj.complete([{'role': 'user', 'content': 'Fix.'}])
    finally:
        obj.close()
