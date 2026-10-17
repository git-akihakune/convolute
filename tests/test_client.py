from argparse import Namespace
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from convolute.client import TranslationClient, TranslationError
from convolute.config import resolve_settings
from conftest import completion


def settings(server, **kwargs):
    return replace(resolve_settings(Namespace(endpoint=server.endpoint),{}), **kwargs)


@pytest.mark.parametrize('mode', ['faithful','creative'])
def test_real_request_and_prompt(server, mode):
    server.responses.append((200,completion('"你好"\n\n42'),{}))
    with TranslationClient(settings(server,mode=mode,api_key='test-key')) as client:
        assert client.translate('Bonjour\n\n42','fr','zh') == '"你好"\n\n42'
    req = server.requests[0]
    assert req['path'] == '/v1/chat/completions'
    assert req['headers']['Authorization'] == 'Bearer test-key'
    assert req['body']['model'] == 'qwen2.5:7b' and req['body']['stream'] is False
    assert 'temperature' not in req['body']
    messages = req['body']['messages']
    assert [m['role'] for m in messages] == ['system','user']
    assert messages[1]['content'] == 'Bonjour\n\n42'
    assert 'French' in messages[0]['content'] and 'Chinese' in messages[0]['content']
    assert 'negation' in messages[0]['content']
    assert ('freer' in messages[0]['content']) == (mode == 'creative')


def test_custom_base_and_temperature_without_auth(server):
    with TranslationClient(settings(server,endpoint=server.endpoint+'/custom',temperature=0.7)) as client:
        assert client.translate('x','en','fr') == 'translated'
    req = server.requests[0]
    assert req['path'] == '/v1/custom/chat/completions'
    assert req['body']['temperature'] == 0.7
    assert 'Authorization' not in req['headers']


@pytest.mark.parametrize('payload', [
    b'not json', {}, [], None, {'choices':[]}, {'choices':[None]},
    completion(''), completion('  '), completion(None), completion(['text']),
    {'choices':[{'finish_reason':'length','message':{'content':'partial'}}]},
    {'choices':[{'message':{'content':'no finish'}}]},
    completion('refused',refusal='No'), completion('tools',tool_calls=[{'id':'x'}]),
    completion('legacy',function_call={'name':'x'}),
])
def test_invalid_completions_fail_safely(server,payload):
    server.responses.append((200,payload,{}))
    with TranslationClient(settings(server)) as client, pytest.raises(TranslationError) as error:
        client.translate('private input','en','fr')
    assert 'private input' not in str(error.value)
    assert error.value.code in ('invalid_response','incomplete_response')


@pytest.mark.parametrize('status',[302,400,401,404,413,422,429,500,502,503,504])
def test_http_failure_is_not_retried_by_default(server,status):
    server.responses.append((status,{'error':'private input SECRET'}, {'Location':server.endpoint}))
    with TranslationClient(settings(server,api_key='SECRET')) as client, pytest.raises(TranslationError) as error:
        client.translate('private input','en','fr')
    assert len(server.requests) == 1
    assert 'SECRET' not in str(error.value) and 'private input' not in str(error.value)


@pytest.mark.parametrize('status',[429,502,503,504])
def test_opted_in_retry_and_backoff(server,status):
    server.responses.extend([(status,{},{}),(status,{},{}),(200,completion('ok'),{})])
    delays = []
    with TranslationClient(settings(server,retries=2),sleep=delays.append) as client:
        assert client.translate('x','en','fr') == 'ok'
    assert delays == [1,2] and len(server.requests) == 3


@pytest.mark.parametrize('header,delay', [('3',3),('garbage',1),('-5',1),('NaN',1)])
def test_retry_after_values(server,header,delay):
    server.responses.extend([(429,{}, {'Retry-After':header}),(200,completion(),{})])
    delays = []
    with TranslationClient(settings(server,retries=1),sleep=delays.append) as client:
        client.translate('x','en','fr')
    assert delays == [delay]


def test_retry_after_dates_and_maximum(server):
    now = datetime(2026,10,17,tzinfo=timezone.utc)
    server.responses.extend([(429,{}, {'Retry-After':format_datetime(now+timedelta(seconds=5))}),
                             (200,completion(),{})])
    delays = []
    with TranslationClient(settings(server,retries=1),sleep=delays.append,now=lambda:now) as client:
        client.translate('x','en','fr')
    assert delays == [5]
    server.responses.append((429,{}, {'Retry-After':'60'}))
    with TranslationClient(settings(server,retries=1),sleep=delays.append) as client, pytest.raises(TranslationError):
        client.translate('x','en','fr')
    assert len(server.requests) == 3 and delays == [5]


@pytest.mark.parametrize('exception,retried', [
    (httpx.ConnectError,True), (httpx.ConnectTimeout,True),
    (httpx.ReadTimeout,False), (httpx.WriteTimeout,False),
])
def test_transport_failures(exception,retried):
    calls = []
    def handler(request):
        calls.append(request)
        raise exception('private SECRET')
    config = resolve_settings(Namespace(retries=1),{})
    with TranslationClient(config,transport=httpx.MockTransport(handler),sleep=lambda _:None) as client:
        with pytest.raises(TranslationError) as error:
            client.translate('private','en','fr')
    assert len(calls) == (2 if retried else 1)
    assert 'SECRET' not in str(error.value)


def test_retry_budget_and_nonretryable_status(server):
    server.responses.extend([(503,{},{}),(503,{},{}),(200,completion(),{})])
    with TranslationClient(settings(server,retries=1),sleep=lambda _:None) as client, pytest.raises(TranslationError):
        client.translate('x','en','fr')
    assert len(server.requests) == 2
    server.responses.clear()
    server.responses.append((500,{},{}))
    with TranslationClient(settings(server,retries=3),sleep=lambda _:None) as client, pytest.raises(TranslationError):
        client.translate('x','en','fr')
    assert len(server.requests) == 3
