import pytest

from convolute.languages import LANGUAGES
from convolute.terminal import (LANGUAGE_COLORS, Painter, clip, detect_capabilities,
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
