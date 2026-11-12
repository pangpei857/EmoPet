"""Targeted GSMTC access on an asyncio worker; no global media keys."""
import asyncio
from queue import Empty,Queue
import threading
import time

from PySide6.QtCore import QObject,Signal,Slot

from .music_core import MusicState,clean_text,is_qq_music


class _MusicWorker:
    def __init__(self,publish,complete):
        self.publish=publish;self.complete=complete;self.commands=Queue(maxsize=1)
        self.stop_event=threading.Event();self.loop=None;self.task=None;self.wakeup=None
        self.thread=threading.Thread(target=self.run,name='qq-music-media',daemon=True)
        self.session=None;self.session_id='';self.serial=0;self.manager=None
        self.manager_tokens=[];self.session_tokens=[];self.sessions_dirty=True;self.media_dirty=True
        self.title='';self.artist='';self.last_state=None;self.media_checked=0.

    def start(self):self.thread.start()

    def wake(self,sessions=False,media=False):
        def mark():
            self.sessions_dirty|=sessions;self.media_dirty|=media
            if self.wakeup is not None:self.wakeup.set()
        if self.loop is not None:
            try:self.loop.call_soon_threadsafe(mark)
            except RuntimeError:pass

    def stop(self):
        self.stop_event.set()
        if self.loop is not None and self.task is not None:
            try:self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:pass
        if self.thread.is_alive():self.thread.join(1.)

    def send(self,request,action,session_id):
        if self.stop_event.is_set() or self.commands.full():return False
        self.commands.put_nowait((request,action,session_id));self.wake();return True

    def emit(self,state):
        if not self.stop_event.is_set() and state!=self.last_state:
            self.last_state=state;self.publish(state)

    @staticmethod
    def unsubscribe(tokens):
        while tokens:
            remove,token=tokens.pop()
            try:remove(token)
            except Exception:pass

    def bind(self,session):
        self.unsubscribe(self.session_tokens)
        self.session=session;self.serial+=1;self.title='';self.artist='';self.media_dirty=True
        self.session_id=f'{session.source_app_user_model_id}:{self.serial}' if session is not None else ''
        if session is not None:
            for add,remove,media in (
                (session.add_media_properties_changed,session.remove_media_properties_changed,True),
                (session.add_playback_info_changed,session.remove_playback_info_changed,False)):
                token=add(lambda *args,m=media:self.wake(media=m))
                self.session_tokens.append((remove,token))

    def select_session(self):
        sessions=[s for s in self.manager.get_sessions() if is_qq_music(s.source_app_user_model_id)]
        def playing(s):
            try:return int(s.get_playback_info().playback_status)==4
            except Exception:return False
        candidate=next((s for s in sessions if playing(s)),sessions[0] if sessions else None)
        if self.sessions_dirty or (candidate is None)!=(self.session is None):self.bind(candidate)
        elif candidate is not None and self.session is not None:
            if candidate.source_app_user_model_id!=self.session.source_app_user_model_id:self.bind(candidate)
        self.sessions_dirty=False

    def snapshot(self):
        if self.session is None:return MusicState(message='未发现 QQ 音乐媒体会话')
        info=self.session.get_playback_info();controls=info.controls
        status={4:'playing',5:'paused'}.get(int(info.playback_status),'stopped')
        toggle=bool(controls.is_play_pause_toggle_enabled or
            (controls.is_pause_enabled if status=='playing' else controls.is_play_enabled))
        return MusicState(self.session_id,self.title,self.artist,status,toggle,
            bool(controls.is_previous_enabled),bool(controls.is_next_enabled),
            'QQ 音乐 · '+{'playing':'播放中','paused':'已暂停','stopped':'未播放'}[status])

    async def execute(self,request,action,token):
        ok=False;message='QQ 音乐会话已变化，请重试。'
        try:
            if self.session is not None and token==self.session_id:
                state=self.snapshot();method=None
                if action=='previous' and state.can_previous:method=self.session.try_skip_previous_async
                elif action=='next' and state.can_next:method=self.session.try_skip_next_async
                elif action=='toggle' and state.can_toggle:
                    controls=self.session.get_playback_info().controls
                    if state.status=='playing' and controls.is_pause_enabled:method=self.session.try_pause_async
                    elif state.status=='paused' and controls.is_play_enabled:method=self.session.try_play_async
                    elif controls.is_play_pause_toggle_enabled:method=self.session.try_toggle_play_pause_async
                if method is not None:
                    ok=bool(await asyncio.wait_for(method(),3.))
                    message='' if ok else 'QQ 音乐没有接受操作，请重试。'
                else:message='QQ 音乐当前不支持此操作。'
        except asyncio.CancelledError:raise
        except Exception:message='音乐控制暂时失败，请在 QQ 音乐中确认播放状态。'
        if not self.stop_event.is_set():self.complete(request,ok,message)
        self.media_dirty=True

    async def watch(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        self.loop=asyncio.get_running_loop();self.task=asyncio.current_task();self.wakeup=asyncio.Event()
        self.manager=await asyncio.wait_for(GlobalSystemMediaTransportControlsSessionManager.request_async(),6.)
        token=self.manager.add_sessions_changed(lambda *args:self.wake(sessions=True))
        self.manager_tokens.append((self.manager.remove_sessions_changed,token))
        checked=0.
        try:
            while not self.stop_event.is_set():
                self.wakeup.clear()
                try:
                    if self.sessions_dirty or time.monotonic()-checked>2.:
                        self.select_session();checked=time.monotonic()
                    if self.session is not None and (self.media_dirty or time.monotonic()-self.media_checked>5.):
                        self.media_dirty=False
                        props=await asyncio.wait_for(self.session.try_get_media_properties_async(),3.)
                        self.title=clean_text(props.title,512);self.artist=clean_text(props.artist)
                        self.media_checked=time.monotonic()
                    try:request,action,session_id=self.commands.get_nowait()
                    except Empty:pass
                    else:await self.execute(request,action,session_id)
                    self.emit(self.snapshot())
                except asyncio.CancelledError:raise
                except Exception:
                    self.emit(MusicState(status='error',message='媒体会话暂不可用，正在重新检测'))
                    try:request,action,token=self.commands.get_nowait()
                    except Empty:pass
                    else:self.complete(request,False,'音乐信息暂不可用，请重试。')
                    self.sessions_dirty=True;self.media_dirty=True
                try:await asyncio.wait_for(self.wakeup.wait(),.75)
                except asyncio.TimeoutError:pass
        finally:
            self.unsubscribe(self.session_tokens);self.unsubscribe(self.manager_tokens)
            self.session=None;self.manager=None

    def run(self):
        try:asyncio.run(self.watch())
        except asyncio.CancelledError:pass
        except Exception:
            self.emit(MusicState(status='error',message='无法读取系统媒体会话，请重新检测 QQ 音乐'))
        finally:self.loop=None;self.task=None


class MusicController(QObject):
    state_changed=Signal(object)
    busy_changed=Signal(bool)
    command_finished=Signal(bool,str)
    _incoming=Signal(int,object)
    _completed=Signal(int,int,bool,str)

    def __init__(self,parent=None,worker_factory=_MusicWorker):
        super().__init__(parent)
        self._factory=worker_factory;self._worker=None;self._generation=0;self._request=0
        self._pending=None;self._closed=False;self.state=MusicState()
        self._incoming.connect(self.receive);self._completed.connect(self.complete)

    def start(self):
        if self._closed or self._worker is not None:return
        self._generation+=1;generation=self._generation
        def emit(state):
            try:self._incoming.emit(generation,state)
            except RuntimeError:pass
        def complete(request,ok,message):
            try:self._completed.emit(generation,request,ok,message)
            except RuntimeError:pass
        self._worker=self._factory(emit,complete)
        self.state=MusicState(status='connecting',message='正在检测 QQ 音乐…');self.state_changed.emit(self.state)
        self._worker.start()

    @Slot(int,object)
    def receive(self,generation,state):
        if generation!=self._generation or self._worker is None:return
        self.state=state;self.state_changed.emit(state)

    def command(self,action,session_id):
        if self._worker is None or self._pending is not None or session_id!=self.state.session_id:return False
        allowed={'previous':self.state.can_previous,'next':self.state.can_next,'toggle':self.state.can_toggle}
        if not allowed.get(action,False):return False
        self._request+=1;self._pending=self._request;self.busy_changed.emit(True)
        if not self._worker.send(self._request,action,session_id):
            self._pending=None;self.busy_changed.emit(False);return False
        return True

    @Slot(int,int,bool,str)
    def complete(self,generation,request,ok,message):
        if generation!=self._generation or request!=self._pending:return
        self._pending=None;self.busy_changed.emit(False);self.command_finished.emit(ok,message)

    def stop(self):
        self._generation+=1;worker=self._worker;self._worker=None;self._pending=None
        if worker is not None:worker.stop()
        self.state=MusicState(message='QQ 音乐联动已关闭')
        self.busy_changed.emit(False);self.state_changed.emit(self.state)

    def retry(self):self.stop();self.start()

    @Slot()
    def shutdown(self):self._closed=True;self.stop()
