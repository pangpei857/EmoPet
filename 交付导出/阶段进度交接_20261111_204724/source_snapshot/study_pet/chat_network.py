"""Asynchronous Qt HTTP transport for DeepSeek Chat Completions."""
import json
from PySide6.QtCore import QByteArray,QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkReply,QNetworkRequest
from .chat_core import CompletionParser,http_error,request_body


class ChatClient(QObject):
    chunk=Signal(str)
    thinking=Signal()
    completed=Signal(str,str)
    failed=Signal(str)
    stopped=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent);self.manager=QNetworkAccessManager(self);self.reply=None
        self.timeout=QTimer(self);self.timeout.setSingleShot(True);self.timeout.timeout.connect(self._timed_out)
        self.parser=None;self.body=b'';self.cancelled=False;self.problem='';self.probe=False
        self._finishing=False

    @property
    def busy(self):return self.reply is not None

    def start(self,config,key,messages,purpose='chat',probe=False):
        if self.busy:return False
        endpoint=config.validate()
        if not key.strip():raise ValueError('请先在模型配置中填写DeepSeek API Key。')
        request=QNetworkRequest(QUrl(endpoint))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
        request.setRawHeader(b'Accept',b'application/json' if probe else b'text/event-stream')
        request.setRawHeader(b'Authorization',b'Bearer '+key.strip().encode('utf-8'))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(60000)
        self.parser=CompletionParser();self.body=b'';self.cancelled=False;self.problem='';self.probe=probe
        reply=self.manager.post(request,QByteArray(json.dumps(request_body(config,messages,purpose=purpose,probe=probe),ensure_ascii=False).encode('utf-8')))
        self.reply=reply
        reply.readyRead.connect(lambda:self._read(reply))
        reply.finished.connect(lambda:self._finished(reply))
        self.timeout.start(240000 if config.thinking and not probe else 120000)
        return True

    def _read(self,reply):
        if reply is not self.reply:return
        data=bytes(reply.readAll())
        if not data:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        content_type=bytes(reply.rawHeader('Content-Type')).lower()
        if status!=200 or self.probe or b'application/json' in content_type:
            self.body+=data
            if len(self.body)>2*1024*1024:self.problem='服务返回的数据过大。';reply.abort()
            return
        try:
            before=self.parser.reasoning;part=self.parser.feed(data)
            if part:self.chunk.emit(part)
            if not before and self.parser.reasoning:self.thinking.emit()
        except ValueError as error:self.problem=str(error);reply.abort()

    def _finished(self,reply):
        if reply is not self.reply or self._finishing:return
        self._finishing=True
        self._read(reply);self.timeout.stop()
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        network_error=reply.error();self.reply=None
        answer=self.parser.answer;reason=self.parser.finish_reason or 'stop'
        error=self.problem
        if self.cancelled:result=('stopped',answer)
        elif error:result=('failed',error)
        elif isinstance(status,int) and status!=200:
            result=('failed','接口发生重定向，请直接填写最终的服务地址。' if 300<=status<400 else http_error(status))
        else:
            try:
                if self.body:
                    self.parser._payload(self.body);self.parser.done=True
                else:
                    part=self.parser.finish()
                    if part:self.chunk.emit(part)
                answer=self.parser.answer;reason=self.parser.finish_reason or 'stop'
                if network_error!=QNetworkReply.NetworkError.NoError and not self.parser.done:
                    raise ValueError('网络连接中断或无法连接，请检查网络、代理与服务地址后重试。')
                if not self.parser.done and self.parser.finish_reason is None:raise ValueError('回答传输中断，已保留收到的部分，可重新发送。')
                if not answer.strip():raise ValueError('模型没有返回可显示的回答，请重试或调整模型设置。')
                result=('completed',(answer,reason))
            except ValueError as error:result=('failed',str(error))
        reply.deleteLater()
        self._finishing=False
        kind,payload=result
        if kind=='completed':self.completed.emit(*payload)
        elif kind=='stopped':self.stopped.emit(payload)
        else:self.failed.emit(payload)

    def stop(self):
        if self.reply is not None:self.cancelled=True;self.reply.abort()

    def _timed_out(self):
        if self.reply is not None:self.problem='等待模型回答超时，已保留收到的内容。请稍后重试。';self.reply.abort()
