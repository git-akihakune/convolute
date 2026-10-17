import io
import json
import os
import subprocess
import sys

import pytest

from convolute.cli import main
from conftest import completion


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ('CONVOLUTE_ENDPOINT','CONVOLUTE_MODEL','CONVOLUTE_MODE','CONVOLUTE_API_KEY'):
        monkeypatch.delenv(name, raising=False)


def invoke(args, data=None, env=None):
    return subprocess.run([sys.executable,'-m','convolute',*args],input=data,
                          capture_output=True,env=env,timeout=10)


def test_help_and_version_do_not_contact_endpoint():
    result = invoke(['--help'])
    assert result.returncode == 0 and b'--preset' in result.stdout and b'--mode' in result.stdout
    assert invoke(['--version']).stdout.strip() == b'convolute 0.1.0'


def test_dry_run_has_default_chain_and_no_input_or_key(monkeypatch,capsys):
    monkeypatch.setenv('CONVOLUTE_API_KEY','PRIVATEKEY')
    assert main(['--dry-run','private text']) == 0
    output = capsys.readouterr()
    plan = json.loads(output.out)
    assert plan['total_calls'] == 5 and plan['mode'] == 'faithful'
    assert plan['chain'] == ['en','fr','de','ja','es','en']
    assert plan['input_characters'] == 12 and plan['preset'] == 'long'
    assert 'PRIVATEKEY' not in output.out and 'private text' not in output.out
    assert output.err == ''


@pytest.mark.parametrize('args', [
    ['--dry-run','--json','x'], ['--dry-run','--show-steps','x'],
    ['--preset','short','--chain','en,fr,en','x'], ['--repeat','0','x'],
    ['--timeout','nan','x'], ['--temperature','inf','x'], ['--mode','wild','x'],
    ['--file','missing.txt','x'], ['--chain','en,,en','x'], ['   '],
])
def test_invalid_cli_arguments(args):
    result = invoke(args)
    assert result.returncode == 2 and result.stdout == b'' and b'Traceback' not in result.stderr


@pytest.mark.parametrize('source',['positional','stdin','file','explicit-stdin'])
def test_utf8_input_methods_and_final_only_stdout(server,tmp_path,source):
    text = '你好\n\nThe meeting is at 14:00.'
    server.responses.extend([(200,completion('intermediate'),{}),(200,completion('final 你好'),{})])
    args = ['--endpoint',server.endpoint,'--preset','short']
    data = None
    if source == 'positional':
        args.append(text)
    elif source in ('stdin','explicit-stdin'):
        data = text.encode()
        if source == 'explicit-stdin':
            args += ['--file','-']
    else:
        path = tmp_path/'corpus.txt'
        path.write_text(text,encoding='utf-8')
        args += ['--file',str(path)]
    result = invoke(args,data)
    assert result.returncode == 0 and result.stdout.decode() == 'final 你好\n'
    assert result.stderr == b''
    assert server.requests[0]['body']['messages'][1]['content'] == text
    assert server.requests[1]['body']['messages'][1]['content'] == 'intermediate'


def test_default_run_and_json_auth_environment(server):
    env = {**os.environ,'CONVOLUTE_ENDPOINT':server.endpoint,
           'CONVOLUTE_MODEL':'custom','CONVOLUTE_MODE':'creative','CONVOLUTE_API_KEY':'PRIVATEKEY'}
    result = invoke(['--json','text'],env=env)
    record = json.loads(result.stdout)
    assert result.returncode == 0 and record['status'] == 'success'
    assert len(record['steps']) == 5 and len(server.requests) == 5
    assert record['model'] == 'custom' and record['mode'] == 'creative'
    assert b'PRIVATEKEY' not in result.stdout and b'PRIVATEKEY' not in result.stderr
    assert all(req['headers']['Authorization'] == 'Bearer PRIVATEKEY' for req in server.requests)
    assert all('freer' in req['body']['messages'][0]['content'] for req in server.requests)


def test_alias_chain_repeats_and_steps_on_stderr(server):
    result = invoke(['--endpoint',server.endpoint,'--chain','EN,CN,KR,JP,ID,EN',
                     '--repeat','2','--show-steps','text'])
    assert result.returncode == 0 and result.stdout == b'translated\n'
    assert len(server.requests) == 10
    assert b'pass 2, step 5: id -> en' in result.stderr
    assert all(len(req['body']['messages']) == 2 for req in server.requests)


@pytest.mark.parametrize('structured',[False,True])
def test_mid_chain_failure_cannot_look_like_success(server,structured):
    server.responses.extend([(200,completion('partial'),{}),(401,{'error':'PRIVATEKEY'}, {})])
    args = ['--endpoint',server.endpoint,'x'] + (['--json'] if structured else [])
    result = invoke(args)
    assert result.returncode == 1 and len(server.requests) == 2
    assert b'PRIVATEKEY' not in result.stderr and b'PRIVATEKEY' not in result.stdout
    if structured:
        record = json.loads(result.stdout)
        assert record['output'] is None and record['status'] == 'error'
        assert len(record['steps']) == 1 and record['error']['step_number'] == 2
    else:
        assert result.stdout == b'' and b'fr -> de' in result.stderr


def test_bad_utf8_stdin_and_file(tmp_path):
    assert invoke(['--dry-run'],b'\xff').returncode == 2
    path = tmp_path/'bad.txt'
    path.write_bytes(b'\xff')
    result = invoke(['--dry-run','--file',str(path)])
    assert result.returncode == 2 and b'UTF-8' in result.stderr and b'Traceback' not in result.stderr


def test_no_input_on_terminal_shows_usage(monkeypatch,capsys):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(sys,'stdin',Terminal())
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2 and 'usage:' in capsys.readouterr().err


def test_leading_dash_text_and_extended_preset():
    result = invoke(['--dry-run','--preset','extended','--repeat','2','--','-text'])
    record = json.loads(result.stdout)
    assert result.returncode == 0 and record['total_calls'] == 18 and record['input_characters'] == 5


def test_interrupt_and_broken_pipe(monkeypatch,capsys):
    class Interrupted(io.StringIO):
        def read(self,*_):
            raise KeyboardInterrupt
    monkeypatch.setattr(sys,'stdin',Interrupted())
    assert main(['--file','-']) == 130
    assert 'interrupted' in capsys.readouterr().err
    class Broken(io.StringIO):
        def write(self,*_):
            raise BrokenPipeError
    monkeypatch.setattr(sys,'stdout',Broken())
    assert main(['--dry-run','x']) == 1


@pytest.mark.parametrize('stream',['stdout','stderr'])
def test_real_closed_output_pipe_exits_cleanly(server,stream):
    reader,writer = os.pipe()
    os.close(reader)
    args = ['--dry-run','x'] if stream == 'stdout' else [
        '--endpoint',server.endpoint,'--preset','short','--show-steps','x']
    try:
        result = subprocess.run(
            [sys.executable,'-m','convolute',*args],
            stdout=writer if stream == 'stdout' else subprocess.PIPE,
            stderr=writer if stream == 'stderr' else subprocess.PIPE,
            timeout=10,
        )
    finally:
        os.close(writer)
    assert result.returncode == 1
    captured = result.stderr if stream == 'stdout' else result.stdout
    assert b'Traceback' not in captured
    if stream == 'stderr':
        assert result.stdout == b'' and len(server.requests) == 1
