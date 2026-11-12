"""Qt supervisor for a bounded, disposable local vision process."""
import multiprocessing as mp
from queue import Empty
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .vision_worker import capture_loop, enumerate_devices


class VisionController(QObject):
    state_changed=Signal(str,str)
    devices_changed=Signal(object)
    frame_ready=Signal(object)
    observation_ready=Signal(object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.context=mp.get_context('spawn')
        self.process=None;self.queue=None;self.preview_queue=None;self.stop_event=None
        self.scanner=None;self.scan_queue=None;self.scan_started=0.
        self.state='off';self.message='摄像头已关闭';self._stopping_since=None
        self._last_frame=None;self._started_at=None;self._terminal_message=False
        self._video_mode=False;self._scan_received=False
        self._last_observation=None;self._ready_at=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll)

    @property
    def active(self):return self.state in {'starting','running','stopping'}

    def set_state(self,state,text):
        self.state=state;self.message=text;self.state_changed.emit(state,text)

    def refresh_devices(self):
        if self.scanner is not None:return
        self.scan_queue=self.context.Queue(maxsize=1)
        self.scanner=self.context.Process(target=enumerate_devices,args=(self.scan_queue,),daemon=True)
        try:self.scanner.start()
        except Exception:
            self.scanner=None;self.close_queue(self.scan_queue);self.scan_queue=None
            self.devices_changed.emit([]);return
        self.scan_started=time.monotonic();self.timer.start(50)
        self._scan_received=False

    def start(self,source,backend=700):
        if self.process is not None:return False
        self.queue=self.context.Queue(maxsize=8);self.preview_queue=self.context.Queue(maxsize=2)
        self.stop_event=self.context.Event()
        self._stopping_since=None;self._last_frame=None;self._started_at=time.monotonic();self._terminal_message=False
        self._video_mode=isinstance(source,str)
        self._last_observation=None;self._ready_at=None
        self.process=self.context.Process(target=capture_loop,
            args=(self.queue,self.stop_event,source,backend,self.preview_queue),daemon=True)
        self.set_state('starting','正在打开本地视频…' if isinstance(source,str) else '正在打开摄像头…')
        try:self.process.start()
        except Exception:
            self.process=None;self.close_queue(self.queue);self.close_queue(self.preview_queue)
            self.queue=None;self.preview_queue=None
            self.set_state('error','无法启动识别进程，请重试。');return False
        self.timer.start(30);return True

    def stop(self):
        if self.process is None:
            self.set_state('off','摄像头已关闭');return
        self.stop_event.set();self._stopping_since=time.monotonic()
        self.set_state('stopping','正在关闭摄像头…')

    def poll(self):
        now=time.monotonic()
        if self.scanner is not None:
            try:
                result=self.scan_queue.get_nowait();self._scan_received=True;self.devices_changed.emit(result.get('items',[]))
            except Empty:pass
            if not self.scanner.is_alive() or now-self.scan_started>10:
                if self.scanner.is_alive():self.scanner.terminate()
                self.scanner.join(.1);self.scanner.close();self.scanner=None
                self.close_queue(self.scan_queue);self.scan_queue=None
                if not self._scan_received:self.devices_changed.emit([])
        if self.process is not None:
            # Results and previews have separate bounded channels. A fast
            # preview must never evict a detection, error, or shutdown message.
            newest=None;observation=None
            for _ in range(32):
                try:item=self.queue.get_nowait()
                except Empty:break
                kind=item.get('type')
                if self._stopping_since is not None:continue
                if kind=='observation':
                    observation=item['observation'];self._last_observation=now
                elif kind in {'status','ready'}:
                    if kind=='ready':self._ready_at=now
                    self.set_state('running' if kind=='ready' else 'starting',item['text'])
                elif kind in {'error','ended'}:
                    self._terminal_message=True
                    self.set_state('error' if kind=='error' else 'off',item['text'])
            for _ in range(6):
                try:item=self.preview_queue.get_nowait()
                except Empty:break
                if self._stopping_since is None:
                    newest=item;self._last_frame=now
            if observation is not None and self.state=='running':
                self.observation_ready.emit(observation.freshened(now))
            if newest is not None and self.state=='running':self.frame_ready.emit(newest)
            if self._stopping_since is not None and now-self._stopping_since>2.5 and self.process.is_alive():
                self.process.terminate()
            elif self._stopping_since is None and self.process.is_alive():
                reference=self._last_frame if self._last_frame is not None else self._started_at
                limit=12 if self._last_frame is not None else 35
                analysis_reference=self._last_observation if self._last_observation is not None else self._ready_at
                analysis_stalled=analysis_reference is not None and now-analysis_reference>8
                if now-reference>limit or analysis_stalled:
                    message='识别响应超时，已停止。请重新开启。' if analysis_stalled else '设备响应超时，已停止。请检查设备后重试。'
                    self._terminal_message=True;self.set_state('error',message)
                    self.stop_event.set();self._stopping_since=now-2.5
            if not self.process.is_alive():
                self.process.join(.1);self.process.close();self.process=None
                self.close_queue(self.queue);self.queue=None;self.stop_event=None
                self.close_queue(self.preview_queue);self.preview_queue=None
                if self._stopping_since is not None and not self._terminal_message:self.set_state('off','摄像头已关闭')
                elif not self._terminal_message:self.set_state('error','识别进程已结束，请重新开启。')
                self._stopping_since=None
        if self.scanner is None and self.process is None:self.timer.stop()

    @staticmethod
    def close_queue(queue):
        if queue is not None:queue.cancel_join_thread();queue.close()

    def shutdown(self):
        self.timer.stop()
        if self.stop_event is not None:self.stop_event.set()
        for process in (self.process,self.scanner):
            if process is not None:
                process.join(.6)
                if process.is_alive():process.terminate();process.join(1.)
                process.close()
        self.process=None;self.scanner=None
        self.close_queue(self.queue);self.close_queue(self.scan_queue)
        self.close_queue(self.preview_queue)
        self.queue=None;self.preview_queue=None;self.scan_queue=None;self.stop_event=None
