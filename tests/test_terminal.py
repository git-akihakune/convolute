import time

import pytest

from convolute.languages import LANGUAGES
from convolute.terminal import (LANGUAGE_COLORS, LiveRegion, Painter, clip, detect_capabilities,
                                strip_ansi, terminal_width, visible_width)
from conftest import FakeStream


@pytest.mark.parametrize('tty,env,platform,encoding,expected',[
    (True,{'TERM':'xterm'},'linux','utf-8',(True,True)),
    (True,{},'darwin','utf-8',(True,True)),
    (True,{'TERM':'dumb'},'linux','utf-8',(False,False)),
    (False,{'TERM':'xterm'},'linux','utf-8',(False,False)),
    (True,{'TERM':'xterm','NO_COLOR':'1'},'linux','utf-8',(True,False)),
    (True,{'TERM':'xterm','NO_COLOR':''},'linux','utf-8',(True,True)),
    (True,{'TERM':'xterm'},'linux','latin-1',(False,False)),
    (True,{'TERM':'xterm'},'win32','utf-8',(False,False)),
    (True,{'WT_SESSION':'x'},'win32','utf-8',(True,True)),
])
def test_capabilities(tty,env,platform,encoding,expected):
    caps = detect_capabilities(FakeStream(tty,encoding),env,platform)
    assert (caps.interactive,caps.color) == expected


def test_language_colors_cover_every_language_and_stay_readable():
    assert set(LANGUAGE_COLORS) == set(LANGUAGES)
    assert not {'30','37','90','97'} & set(LANGUAGE_COLORS.values())


def test_painter_is_plain_without_color_and_strippable_with_it():
    assert Painter(False).ok('x') == 'x' and Painter(False).lang('fr','x') == 'x'
    styled = Painter(True).lang('fr','x')
    assert styled != 'x' and styled.endswith('\x1b[0m') and strip_ansi(styled) == 'x'


def test_width_and_clip_handle_escapes_and_double_width_text():
    assert visible_width('\x1b[31mabc\x1b[0m') == 3 and visible_width('会議は') == 6
    assert clip('abc',3) == 'abc' and clip('abc',0) == ''
    assert clip('\x1b[31mabcdef\x1b[0m',4) == '\x1b[31mabc…\x1b[0m'
    assert clip('会議は金曜日',7) == '会議は…'
    assert visible_width(clip('x'*100+'会',20)) <= 20


def test_terminal_width_falls_back_without_a_terminal():
    assert terminal_width(FakeStream()) == 80


def test_block_is_redrawn_in_place():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.start(lambda now: ['one','two']); region.tick(); region.tick()
    out = stream.getvalue()
    assert out.startswith('\x1b[?25l') and out.count('\x1b[1A') == 1 and 'one\ntwo' in out
    assert region.columns() == 40


def test_print_above_scrolls_text_and_keeps_the_block_below():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.start(lambda now: ['spin']); region.tick(); region.print_above('done line')
    assert strip_ansi(stream.getvalue()).replace('\r','').endswith('done line\nspin')


def test_print_above_works_before_the_region_starts():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.print_above('header')
    assert stream.getvalue() == 'header\n'


def test_finish_leaves_final_lines_and_restores_the_cursor_once():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.start(lambda now: ['spin']); region.tick(); region.finish(['final'])
    out = stream.getvalue(); region.close()
    assert out.endswith('final\n\x1b[?25h') and stream.getvalue() == out


def test_lines_are_clipped_to_one_column_less_than_the_width():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 10,threaded=False)
    region.start(lambda now: ['x'*50,'会'*30]); region.tick()
    rows = strip_ansi(stream.getvalue()).replace('\r','').split('\n')
    assert max(visible_width(row) for row in rows) <= 9


def test_stream_errors_never_escape():
    class Failing(FakeStream):
        def write(self,*_):
            raise BrokenPipeError
    region = LiveRegion(Failing(),width=lambda: 40,threaded=False)
    region.start(lambda now: ['x']); region.tick(); region.print_above('y'); region.finish(['z']); region.close()


def test_thread_animates_until_finished():
    frames = []
    region = LiveRegion(FakeStream(),width=lambda: 40,interval=0.01)
    region.start(lambda now: frames.append(now) or ['x'])
    deadline = time.monotonic()+2
    while len(frames) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    region.finish(); count = len(frames); time.sleep(0.05)
    assert count >= 3 and len(frames) == count
