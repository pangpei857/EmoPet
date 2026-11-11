"""Loopback-only deterministic DeepSeek protocol fixture for automated checks."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
import time

PLAN={'summary':'先理解概念，再做练习，最后回顾。','steps':[
    {'title':'浏览第三章，标出不懂的概念','minutes':10},
    {'title':'完成两道例题并写下思路','minutes':15},
    {'title':'合上书，回顾三个关键点','minutes':5}]}
ANSWER='我们先把目标缩小一点。\n1. 用5分钟浏览第三章的小标题。\n2. 选一个不懂的概念，写下你的问题。\n3. 完成后再继续下一步，我会陪着你。'


class _Server(ThreadingHTTPServer):
    daemon_threads=True


@contextmanager
def local_model():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            self.server.requests.append(body)
            mode=self.server.mode
            if mode=='auth':
                self.send_response(401);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'error':{'message':'do-not-echo-api-key'}}).encode());return
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream' if body.get('stream') else 'application/json');self.end_headers()
            if not body.get('stream'):
                self.wfile.write(json.dumps({'choices':[{'message':{'content':'连接成功'},'finish_reason':'stop'}]},ensure_ascii=False).encode());return
            def event(delta=None,reason=None):
                value={'choices':[{'index':0,'delta':delta or {},'finish_reason':reason}]}
                data=('data: '+json.dumps(value,ensure_ascii=False)+'\r\n\r\n').encode('utf-8')
                middle=max(1,len(data)//2)
                self.wfile.write(data[:middle]);self.wfile.flush();time.sleep(.003)
                self.wfile.write(data[middle:]);self.wfile.flush()
            try:
                if mode=='bad':self.wfile.write(b'data: invalid\n\n');self.wfile.flush();return
                event({'reasoning_content':'TEST_REASONING_NOT_DISPLAYED'})
                answer=json.dumps(PLAN,ensure_ascii=False) if body.get('response_format') else ANSWER
                for index in range(0,len(answer),12):
                    event({'content':answer[index:index+12]})
                    if mode=='disconnect':return
                    if mode=='slow':time.sleep(.2)
                event(reason='stop');self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,OSError):pass
    server=_Server(('127.0.0.1',0),Handler);server.requests=[];server.mode='normal'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server,f'http://127.0.0.1:{server.server_port}'
    finally:server.shutdown();server.server_close();thread.join(2)
