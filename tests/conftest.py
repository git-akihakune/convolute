import io
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest


def completion(text='translated', **message):
    return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text,**message}}]}


class FakeStream(io.StringIO):
    def __init__(self, tty=True, encoding='utf-8'):
        super().__init__()
        self._tty, self._encoding = tty, encoding

    def isatty(self):
        return self._tty

    @property
    def encoding(self):
        return self._encoding


def run_on_pty(args, *, columns=80, env=None, interrupt_when=None):
    """Run the CLI with stderr on a pseudo-terminal; stdout stays a pipe."""
    import fcntl, pty, select, signal, struct, termios
    from convolute.terminal import strip_ansi
    child_env = {name: value for name, value in os.environ.items() if name != 'NO_COLOR'}
    child_env.update({'TERM':'xterm-256color','PYTHONUTF8':'1'})
    child_env.update(env or {})
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',24,columns,0,0))
    proc = subprocess.Popen([sys.executable,'-m','convolute',*args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=slave, env=child_env)
    os.close(slave)
    chunks, interrupted, deadline = [], interrupt_when is None, time.monotonic()+30
    try:
        while time.monotonic() < deadline:
            if select.select([master],[],[],0.05)[0]:
                try:
                    data = os.read(master,4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
                if not interrupted and interrupt_when in strip_ansi(b''.join(chunks).decode('utf-8','replace')):
                    proc.send_signal(signal.SIGINT)
                    interrupted = True
            elif proc.poll() is not None:
                break
        try:
            stdout, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
    finally:
        os.close(master)
    terminal = b''.join(chunks).decode('utf-8','replace').replace('\r\n','\n')
    return SimpleNamespace(returncode=proc.returncode, terminal=terminal, stdout=stdout)


@pytest.fixture
def server():
    state = SimpleNamespace(requests=[], responses=deque(), delay=0.0)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state.requests.append({'path':self.path,'headers':dict(self.headers),'body':body})
            if state.delay:
                time.sleep(state.delay)
            status, payload, headers = state.responses.popleft() if state.responses else (200, completion(), {})
            data = payload if isinstance(payload, bytes) else json.dumps(payload,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            for name,value in headers.items():
                self.send_header(name,value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    worker = threading.Thread(target=httpd.serve_forever,daemon=True)
    worker.start()
    state.endpoint = f'http://127.0.0.1:{httpd.server_port}/v1'
    yield state
    httpd.shutdown()
    httpd.server_close()
    worker.join()
