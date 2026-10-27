import subprocess

import pytest

from convolute.clipboard import ClipboardError, copy_text

JAPANESE = '会議は金曜日に変更されました。'


def everything(name):
    return '/usr/bin/' + name


def fake_run(calls,returncode=0):
    def run(cmd,**kwargs):
        calls.append((cmd,kwargs))
        return subprocess.CompletedProcess(cmd,returncode)
    return run


def test_macos_sends_exact_utf8_bytes_with_a_utf8_locale():
    calls = []
    copy_text(JAPANESE,platform='darwin',environ={},which=everything,run=fake_run(calls))
    cmd,kwargs = calls[0]
    assert cmd == ['/usr/bin/pbcopy'] and kwargs['input'] == JAPANESE.encode()
    assert kwargs['env']['LC_CTYPE'] == 'UTF-8'
    assert kwargs['stdout'] is subprocess.DEVNULL and kwargs['stderr'] is subprocess.DEVNULL


def test_windows_sends_utf16_with_a_byte_order_mark():
    calls = []
    copy_text(JAPANESE,platform='win32',environ={},which=everything,run=fake_run(calls))
    assert calls[0][1]['input'] == ('﻿'+JAPANESE).encode('utf-16-le')


@pytest.mark.parametrize('environ,available,expected',[
    ({'WAYLAND_DISPLAY':'wayland-0'},{'wl-copy','xclip','xsel'},['/usr/bin/wl-copy']),
    ({},{'wl-copy','xclip','xsel'},['/usr/bin/xclip','-selection','clipboard']),
    ({},{'xsel'},['/usr/bin/xsel','--clipboard','--input']),
])
def test_linux_tool_preference(environ,available,expected):
    calls = []
    copy_text('x',platform='linux',environ=environ,which=lambda n: '/usr/bin/'+n if n in available else None,
              run=fake_run(calls))
    assert calls[0][0] == expected and calls[0][1]['input'] == b'x'


def test_failures_raise_clipboard_error():
    with pytest.raises(ClipboardError,match='no clipboard tool'):
        copy_text('x',platform='linux',environ={},which=lambda n: None,run=fake_run([]))
    with pytest.raises(ClipboardError):
        copy_text('x',platform='darwin',environ={},which=everything,run=fake_run([],returncode=3))
    for failure in (subprocess.TimeoutExpired('pbcopy',5),OSError('gone')):
        def run(*_,**__):
            raise failure
        with pytest.raises(ClipboardError):
            copy_text('x',platform='darwin',environ={},which=everything,run=run)
