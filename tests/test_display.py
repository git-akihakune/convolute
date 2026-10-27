import io
from argparse import Namespace

import pytest

from convolute.client import TranslationError
from convolute.config import resolve_settings
from convolute.display import (Display, LogDisplay, PlainDisplay, SpinnerDisplay, is_revealable,
                               make_display, reveal_count)
from convolute.pipeline import Step, run
from convolute.terminal import LiveRegion, Painter, strip_ansi
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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(cls,width=80,color=False,**kwargs):
    out, clock = FakeStream(), FakeClock()
    region = LiveRegion(out,width=lambda: width,clock=clock,threaded=False)
    return out, clock, region, cls(region,Painter(color),clock,**kwargs)


def test_spinner_line_shows_progress_then_a_summary():
    out,clock,region,display = make(SpinnerDisplay)
    display.begin(LONG,37); display.hop_started(1,3,'de','ja'); clock.now = 1.2; region.tick()
    screen = strip_ansi(out.getvalue())
    assert 'de → ja' in screen and 'hop 3/5' in screen and '1.2s' in screen
    clock.now = 10.4; display.end(RESULT_LONG)
    assert strip_ansi(out.getvalue()).endswith('✔ 5 translations · 10.4s\n')


def test_spinner_shows_pass_when_repeating_and_no_summary_on_failure():
    repeated = resolve_settings(Namespace(preset='short',repeat=2),{})
    out,clock,region,display = make(SpinnerDisplay)
    display.begin(repeated,5); display.hop_started(2,1,'en','fr'); region.tick()
    assert 'pass 2/2 · hop 1/2' in strip_ansi(out.getvalue())
    display.end(FAILED); assert '✔' not in strip_ansi(out.getvalue())


def test_make_display_gives_interactive_default_a_spinner():
    display = make_display(quiet=False,verbose=False,steps=False,stream=FakeStream(True),environ={'TERM':'xterm'})
    assert type(display) is SpinnerDisplay; display.close()


def test_reveal_helpers():
    assert reveal_count(300,0.5) == 150 and reveal_count(30,0.25) == 15 and reveal_count(30,9) == 30
    assert is_revealable('Hello there.',80) and not is_revealable('a\nb',80)
    assert not is_revealable('x'*200,80) and not is_revealable('会'*30,40)


def test_verbose_log_commits_each_hop_with_time_and_character_counts():
    out,clock,region,display = make(LogDisplay,steps=False)
    display.begin(LONG,37); display.hop_started(1,1,'en','fr'); clock.now = 2.1
    display.hop_finished(Step(1,1,'en','fr','La réunion a été déplacée à vendredi.',2.1))
    screen = strip_ansi(out.getvalue())
    assert '├ model' in screen and '└ mode' in screen and '[1/5] en → fr  ✔ 2.1s  37 → 37 chars' in screen
    assert 'La réunion' not in screen
    display.end(RESULT_LONG); assert 'done in 2.1s · 5 hops' in strip_ansi(out.getvalue())


def test_log_labels_the_pass_when_repeating():
    repeated = resolve_settings(Namespace(preset='short',repeat=2),{})
    out,clock,region,display = make(LogDisplay,steps=False)
    display.begin(repeated,5); display.hop_started(2,1,'en','fr'); region.tick()
    assert '[p2 1/2] en → fr' in strip_ansi(out.getvalue())


def test_chain_log_reveals_short_text_gradually_then_commits_it():
    out,clock,region,display = make(LogDisplay,steps=True)
    display.begin(LONG,37); display.hop_started(1,2,'fr','de')
    text = 'Das Treffen wurde auf Freitag verschoben.'
    display.hop_finished(Step(1,2,'fr','de',text,1.0)); clock.now = 0.3; region.tick()
    partial = strip_ansi(out.getvalue())
    assert '┃ Das T' in partial and text not in partial
    clock.now = 3; region.tick(); display.end(RESULT_LONG)
    assert text in strip_ansi(out.getvalue())


def test_chain_log_prints_long_multiparagraph_text_whole_and_immediately():
    text = 'Erster Absatz.\n\n' + 'Zweiter Absatz. ' * 300
    out,clock,region,display = make(LogDisplay,steps=True)
    display.begin(LONG,37); display.hop_started(1,1,'en','fr')
    display.hop_finished(Step(1,1,'en','fr',text,1.0))
    screen = strip_ansi(out.getvalue())
    assert all(line in screen for line in text.split('\n')) and screen.count('┃ ') >= 3


def test_make_display_gives_interactive_verbose_a_log():
    display = make_display(quiet=False,verbose=True,steps=True,stream=FakeStream(True),environ={'TERM':'xterm'})
    assert type(display) is LogDisplay; display.close()
