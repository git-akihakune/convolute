from argparse import Namespace

import pytest

from convolute.config import normalize_endpoint, resolve_settings
from convolute.languages import resolve_chain


def test_default_presets_and_aliases():
    assert resolve_chain(None, None) == ('en', 'fr', 'de', 'ja', 'es', 'en')
    assert resolve_chain('short', None) == ('en', 'fr', 'en')
    assert resolve_chain('extended', None) == ('en','fr','de','es','pt','it','zh','ja','ko','en')
    assert resolve_chain(None, ' EN, CN, KR, JP, ID, EN ') == ('en','zh','ko','ja','id','en')


@pytest.mark.parametrize('preset,chain', [
    ('long','en,fr,en'), ('missing',None), (None,'en,fr'), (None,'en,en'),
    (None,'en,,en'), (None,'en,xx,en'), (None,'en,fr,fr,en'), (None,'en'),
])
def test_invalid_chains(preset, chain):
    with pytest.raises(ValueError):
        resolve_chain(preset, chain)


@pytest.mark.parametrize('raw,expected', [
    ('127.0.0.1:11434','http://127.0.0.1:11434/v1'),
    ('localhost:11434','http://localhost:11434/v1'),
    ('[::1]:11434','http://[::1]:11434/v1'),
    ('https://example.org','https://example.org/v1'),
    ('https://example.org/','https://example.org/v1'),
    ('https://example.org/custom/v1/','https://example.org/custom/v1'),
])
def test_endpoint_normalization(raw, expected):
    assert normalize_endpoint(raw) == expected


@pytest.mark.parametrize('raw', [
    'example.org:11434', 'http://', 'ftp://example.org',
    'https://name:secret@example.org/v1', 'http://localhost:99999',
    'http://localhost:bad', 'http://localhost/v1?key=secret',
    'http://localhost/v1#secret', 'http://localhost/v1?',
    'http://localhost/v1/chat/completions/', '', ' http://localhost',
    'http://local host', 'http://localhost/\nsecret',
])
def test_invalid_endpoint_does_not_echo_secrets(raw):
    with pytest.raises(ValueError) as error:
        normalize_endpoint(raw)
    assert 'secret' not in str(error.value)


def test_defaults_and_environment_precedence():
    config = resolve_settings(Namespace(), {})
    assert config.repeat == 1 and config.mode == 'faithful'
    assert config.model == 'qwen2.5:7b'
    assert config.endpoint == 'http://127.0.0.1:11434/v1'
    assert config.timeout == 120 and config.retries == 0 and config.temperature is None
    env = {'CONVOLUTE_ENDPOINT':'https://example.org/api', 'CONVOLUTE_MODEL':'other',
           'CONVOLUTE_MODE':'creative', 'CONVOLUTE_API_KEY':'top-secret'}
    config = resolve_settings(Namespace(), env)
    assert (config.endpoint, config.model, config.mode) == ('https://example.org/api','other','creative')
    assert config.api_key == 'top-secret' and 'top-secret' not in repr(config)
    config = resolve_settings(Namespace(endpoint='localhost:1',model='chosen',mode='faithful'),env)
    assert (config.endpoint,config.model,config.mode) == ('http://localhost:1/v1','chosen','faithful')


@pytest.mark.parametrize('field,value', [
    ('repeat',0),('repeat',-1),('repeat',1.5), ('timeout',0), ('timeout',float('nan')),
    ('timeout',float('inf')), ('retries',-1), ('retries',0.5),
    ('temperature',-0.1), ('temperature',2.1), ('temperature',float('nan')),
    ('temperature',float('inf')), ('model','  '), ('mode','wild'),
])
def test_invalid_settings(field,value):
    with pytest.raises(ValueError):
        resolve_settings(Namespace(**{field:value}),{})


@pytest.mark.parametrize('name', ['CONVOLUTE_ENDPOINT','CONVOLUTE_MODEL','CONVOLUTE_MODE'])
def test_empty_environment_values_are_not_ignored(name):
    with pytest.raises(ValueError):
        resolve_settings(Namespace(),{name:' '})


@pytest.mark.parametrize('key',['SECRET\nvalue','SECRET\x00value','SECRET你好',' SECRET '])
def test_invalid_bearer_key_fails_safely_before_http(key):
    with pytest.raises(ValueError) as error:
        resolve_settings(Namespace(),{'CONVOLUTE_API_KEY':key})
    assert 'SECRET' not in str(error.value)
