"""Local-first summaries; remote generation only follows an explicit user action."""
from PySide6.QtCore import QObject,Signal

from .chat_core import ChatConfig
from .chat_network import ChatClient
from .chat_store import ChatStore
from .history import local_day
from .secrets import KeyVault
from .summary_core import build_facts,local_summary,summary_messages,parse_ai_summary,ai_summary_text


class SummaryService(QObject):
    updated=Signal(str,str)
    status_changed=Signal(str)

    def __init__(self,store,parent=None,client=None):
        super().__init__(parent);self.store=store;self.history=store.history
        # Reading a summary must not mark a live ChatPanel's pending answer as interrupted.
        self.chats=ChatStore(store.path.parent,recover_pending=False)
        self.client=client if client is not None else ChatClient(self)
        self.client.completed.connect(self._completed);self.client.failed.connect(self._failed)
        self.client.stopped.connect(lambda _:self._failed('生成已停止，已保留本地统计版。'))
        self._request=None

    def ensure(self,scope,target):
        facts=build_facts(self.history,self.chats,scope,str(target))
        if facts is None:return None
        self.history.save_learning_summary(scope,str(target),facts,local_summary(facts))
        result=self.history.learning_summary(scope,str(target))
        return result

    def ensure_session(self,session_id):return self.ensure('session',session_id)

    def refresh_daily(self,day=None):return self.ensure('day',day or local_day(self.history.clock()))

    def request_ai(self,scope,target,*,consent=False):
        if not consent:
            self.status_changed.emit('勾选发送选中记录的文字与统计后，再生成DeepSeek复盘。');return False
        if self.client.busy:
            self.status_changed.emit('正在生成另一份复盘，请等待完成。');return False
        record=self.ensure(scope,str(target))
        if not record:return False
        config=ChatConfig.from_dict(self.store.get('chat',{}));config.thinking=False
        try:
            config.validate();vault=KeyVault(self.store.path.parent);key=vault.load(config.base_url)
            if not key:raise ValueError(vault.error or '请先在学习对话的模型配置中保存DeepSeek API Key。')
            messages,ids=summary_messages(record['facts'])
            self._request=(scope,str(target),record['facts_hash'],ids,config.model)
            self.history.save_ai_summary(scope,str(target),record['facts_hash'],status='pending',model=config.model)
            if not self.client.start(config,key,messages,purpose='summary'):
                self._failed('复盘请求未启动，已保留本地统计版。');return False
        except ValueError as error:
            self._failed(str(error));return False
        self.status_changed.emit('正在生成复盘；本地统计版已保存。')
        self.updated.emit(scope,str(target));return True

    def _completed(self,answer,reason):
        if self._request is None:return
        scope,target,digest,ids,model=self._request
        try:
            if reason not in {'stop',''}:raise ValueError('模型复盘未完整返回，已保留本地统计版。')
            data=parse_ai_summary(answer,ids)
            # A late answer may not overwrite a newer facts snapshot after a correction.
            self.ensure(scope,target)
            accepted=self.history.save_ai_summary(scope,target,digest,ai_summary_text(data),model=model)
            message='DeepSeek复盘已保存。' if accepted else '记录已更新，本次旧复盘未覆盖最新统计；可重新生成。'
            self._request=None;self.status_changed.emit(message);self.updated.emit(scope,target)
        except ValueError as error:self._failed(str(error))

    def _failed(self,message):
        if self._request is not None:
            scope,target,digest,_,model=self._request;self._request=None
            self.history.save_ai_summary(scope,target,digest,status='failed',error=message,model=model)
            self.updated.emit(scope,target)
        self.status_changed.emit(str(message))

    def shutdown(self):
        if self.client.busy:self.client.stop()
