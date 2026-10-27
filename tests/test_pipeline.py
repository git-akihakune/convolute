from argparse import Namespace
from dataclasses import asdict

import pytest

from convolute.client import TranslationError
from convolute.config import resolve_settings
from convolute.pipeline import run


def test_repeat_uses_previous_translation_and_records_steps():
    config = resolve_settings(Namespace(chain='en,fr,en',repeat=2),{'CONVOLUTE_API_KEY':'SECRET'})
    calls, steps = [], []
    def translate(text,source,target):
        calls.append((text,source,target))
        return text + f'->{target}'
    result = run('hello\n\n42',config,translate,steps.append)
    assert [(a,b) for _,a,b in calls] == [('en','fr'),('fr','en'),('en','fr'),('fr','en')]
    assert [t for t,_,_ in calls] == ['hello\n\n42','hello\n\n42->fr','hello\n\n42->fr->en','hello\n\n42->fr->en->fr']
    assert result.output == 'hello\n\n42->fr->en->fr->en'
    assert [(s.pass_number,s.step_number) for s in steps] == [(1,1),(1,2),(2,1),(2,2)]
    assert all(s.duration_seconds >= 0 for s in steps)
    assert result.steps == steps and result.status == 'success'
    assert result.schema_version == 1 and result.input == 'hello\n\n42' and result.error is None
    record = asdict(result)
    assert 'SECRET' not in str(record) and 'api_key' not in str(record)
    assert record['request_settings'] == {'timeout':120.0,'retries':0}


@pytest.mark.parametrize('mode',['faithful','creative'])
def test_default_has_five_calls_independent_of_mode(mode):
    calls = []
    def translate(text,source,target):
        calls.append((source,target))
        return '"output"'
    result = run('x',resolve_settings(Namespace(mode=mode),{}),translate)
    assert calls == [('en','fr'),('fr','de'),('de','ja'),('ja','es'),('es','en')]
    assert result.output == '"output"' and result.mode == mode


def test_failure_has_completed_steps_but_no_final_output():
    calls, steps = [], []
    def translate(text,source,target):
        calls.append((source,target))
        if len(calls) == 3:
            raise TranslationError('timeout','request timed out')
        return 'step'
    result = run('x',resolve_settings(Namespace(chain='en,fr,en',repeat=2),{}),translate,steps.append)
    assert len(calls) == 3 and len(steps) == 2 and result.steps == steps
    assert result.status == 'error' and result.output is None
    assert result.error == {'code':'timeout','message':'request timed out','pass_number':2,
                            'step_number':1,'source':'en','target':'fr'}


def test_interrupt_is_not_a_translation_error():
    def translate(*_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run('x',resolve_settings(Namespace(),{}),translate)


def test_on_start_precedes_every_translation_including_the_failing_one():
    events = []
    def translate(text,source,target):
        events.append(('translate',source,target))
        if events.count(('translate','en','fr')) == 2:
            raise TranslationError('timeout','request timed out')
        return 'x'
    run('x',resolve_settings(Namespace(chain='en,fr,en',repeat=2),{}),translate,
        lambda s: events.append(('done',s.pass_number,s.step_number)),
        lambda *hop: events.append(('start',*hop)))
    assert events == [('start',1,1,'en','fr'),('translate','en','fr'),('done',1,1),
                      ('start',1,2,'fr','en'),('translate','fr','en'),('done',1,2),
                      ('start',2,1,'en','fr'),('translate','en','fr')]
