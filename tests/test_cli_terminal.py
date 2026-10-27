import re

import pytest

pytest.importorskip('pty')

from convolute.terminal import strip_ansi, visible_width
from conftest import completion, run_on_pty


def test_default_run_animates_clears_and_leaves_only_the_translation(server):
    server.delay = 0.3
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','short','x'])
    screen = strip_ansi(result.terminal)
    assert result.returncode == 0 and result.stdout == b'translated\n'
    assert 'en → fr' in screen and '✔ 2 translations' in screen
    assert result.terminal.rstrip().endswith('\x1b[?25h')


def test_failure_clears_the_spinner_before_the_error_and_restores_the_cursor(server):
    server.responses.extend([(200,completion('partial'),{}),(401,{'error':'x'},{})]); server.delay = 0.2
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','short','x'])
    assert result.returncode == 1 and result.stdout == b''
    assert 'convolute: pass 1, step 2: fr -> en' in result.terminal
    assert '✔ 2 translations' not in result.terminal
    assert result.terminal.rfind('\x1b[?25h') > result.terminal.rfind('\x1b[?25l')


def test_ctrl_c_mid_hop_exits_130_with_the_cursor_restored(server):
    server.delay = 5
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','short','x'],interrupt_when='en → fr')
    assert result.returncode == 130 and result.stdout == b'' and 'interrupted' in result.terminal
    assert result.terminal.rfind('\x1b[?25h') > result.terminal.rfind('\x1b[?25l')


def test_extended_rail_never_wraps_on_a_narrow_terminal(server):
    server.delay = 0.2
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','extended','--show-steps','x'],columns=60)
    rows = [row for row in re.split(r'[\r\n]',strip_ansi(result.terminal)) if '━' in row or '╌' in row]
    assert result.returncode == 0 and result.stdout == b'translated\n'
    assert rows and all(visible_width(row) <= 59 for row in rows)


def test_quiet_no_color_and_dumb_terminals(server):
    server.delay = 0.2
    base = ['--endpoint',server.endpoint,'--preset','short']
    quiet = run_on_pty([*base,'--quiet','x'])
    assert quiet.terminal == '' and quiet.stdout == b'translated\n'
    plain = run_on_pty([*base,'x'],env={'NO_COLOR':'1'})
    assert '\x1b[?25l' in plain.terminal and not re.search(r'\x1b\[[0-9;]*m',plain.terminal)
    assert '\x1b' not in run_on_pty([*base,'x'],env={'TERM':'dumb'}).terminal
