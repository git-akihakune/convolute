import io
from argparse import Namespace

import pytest

from convolute.client import TranslationError
from convolute.config import resolve_settings
from convolute.display import Display, PlainDisplay, make_display
from convolute.pipeline import Step, run
from conftest import FakeStream


def fail(*_):
    raise TranslationError('timeout','request timed out')


SETTINGS = resolve_settings(Namespace(preset='short'),{})
LONG = resolve_settings(Namespace(),{})
RESULT = run('hello',SETTINGS,lambda *_: 'x')
RESULT_LONG = run('hello',LONG,lambda *_: 'x')
FAILED = run('hello',SETTINGS,fail)


def test_plain_steps_alone_is_byte_compatible_with_the_old_format():
    out = io.StringIO(); display = PlainDisplay(out,verbose=False,steps=True)
    display.begin(SETTINGS,5); display.hop_finished(Step(1,2,'fr','de','Hallo',0.4)); display.end(RESULT)
    assert out.getvalue() == 'pass 1, step 2: fr -> de\nHallo\n\n'


def test_plain_verbose_logs_header_hops_and_summary_without_text():
    out = io.StringIO(); times = iter([0.0,4.2])
    display = PlainDisplay(out,verbose=True,steps=False,clock=lambda: next(times))
    display.begin(SETTINGS,5)
    display.hop_finished(Step(1,1,'en','fr','Bonjour',2.1))
    display.hop_finished(Step(1,2,'fr','en','Hello there',2.0))
    display.end(RESULT)
    text = out.getvalue()
    assert 'qwen2.5:7b' in text and 'en -> fr -> en' in text and 'Bonjour' not in text
    assert 'pass 1, step 1: en -> fr  2.1s  5 -> 7 chars\n' in text
    assert 'pass 1, step 2: fr -> en  2.0s  7 -> 11 chars\n' in text
    assert text.endswith('done in 4.2s, 2 hops\n') and text.isascii()


def test_plain_verbose_with_steps_prints_text_under_each_hop():
    out = io.StringIO(); display = PlainDisplay(out,verbose=True,steps=True)
    display.begin(SETTINGS,5); display.hop_finished(Step(1,1,'en','fr','Bonjour',2.1))
    assert 'pass 1, step 1: en -> fr  2.1s  5 -> 7 chars\nBonjour\n\n' in out.getvalue()


def test_plain_header_stays_ascii_when_repeating():
    out = io.StringIO(); display = PlainDisplay(out,verbose=True,steps=False)
    display.begin(resolve_settings(Namespace(preset='short',repeat=2),{}),5)
    assert 'en -> fr -> en (2 passes)' in out.getvalue() and out.getvalue().isascii()


def test_a_failed_run_prints_no_summary():
    out = io.StringIO(); display = PlainDisplay(out,verbose=True,steps=False)
    display.begin(SETTINGS,1); display.end(FAILED)
    assert 'done in' not in out.getvalue()


@pytest.mark.parametrize('kwargs,tty,expected',[
    ({'quiet':True,'verbose':True,'steps':True},False,Display),
    ({'quiet':False,'verbose':False,'steps':False},False,Display),
    ({'quiet':False,'verbose':False,'steps':True},False,PlainDisplay),
    ({'quiet':False,'verbose':True,'steps':False},False,PlainDisplay),
])
def test_make_display_for_non_interactive_streams(kwargs,tty,expected):
    assert type(make_display(stream=FakeStream(tty),environ={'TERM':'xterm'},**kwargs)) is expected
