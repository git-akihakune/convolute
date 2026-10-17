import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest


def completion(text='translated', **message):
    return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text,**message}}]}


@pytest.fixture
def server():
    state = SimpleNamespace(requests=[], responses=deque())

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state.requests.append({'path':self.path,'headers':dict(self.headers),'body':body})
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
