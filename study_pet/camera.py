"""Qt supervisor for a bounded, disposable local vision process."""
from collections import deque
import logging
import multiprocessing as mp
from queue import Empty
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .vision_profiles import DEFAULT_VISION_PROFILE, VISION_PROFILES
from .vision_worker import capture_loop, enumerate_devices


class VisionController(QObject):
    state_changed=Signal(str,str)
    devices_changed=Signal(object)
    frame_ready=Signal(object)
    observation_ready=Signal(object)
    FIRST_CAMERA_FRAME_TIMEOUT=10.
    FIRST_VIDEO_FRAME_TIMEOUT=18.
    ANALYSIS_START_TIMEOUT=20.
    STOP_GRACE=2.5

    def __init__(self,parent=None):
        super().__init__(parent)
        self.context=mp.get_context('spawn')
        self.process=None;self.queue=None;self.preview_queue=None;self.stop_event=None
        self.scanner=None;self.scan_queue=None;self.scan_started=0.
        self.state='off';self.message='摄像头已关闭';self._stopping_since=None
        self._last_frame=None;self._started_at=None;self._terminal_message=False
        self._video_mode=False;self._scan_received=False
        self._last_observation=None;self._ready_at=None
        self._first_frame=None;self._analysis_message=None;self._pending_sources=deque()
        self._model_profile = DEFAULT_VISION_PROFILE
        self._user_stop=False
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll)

    @property
    def active(self):return self.state in {'starting','previewing','running','stopping'}

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

    def start(self,source,backend=700,*,alternatives=(),model_profile=DEFAULT_VISION_PROFILE):
        if self.process is not None:return False
        if model_profile not in VISION_PROFILES:
            raise ValueError(f'Unknown vision profile: {model_profile}')
        self._model_profile = model_profile
        self._video_mode=isinstance(source,str)
        self._pending_sources=deque([(source,backend,backend==1400)])
        if not self._video_mode:
            endpoints=list(dict.fromkeys(alternatives))
            self._pending_sources.extend((index,api,True) for index,api in endpoints if (index,api)!=(source,backend))
            if len(self._pending_sources)==1 and backend!=1400:
                self._pending_sources.append((source,backend,True))
        return self._open_next()

    def _open_next(self):
        source,backend,native_format=self._pending_sources.popleft()
        self.queue=self.context.Queue(maxsize=8);self.preview_queue=self.context.Queue(maxsize=2)
        self.stop_event=self.context.Event()
        self._stopping_since=None;self._last_frame=None;self._started_at=time.monotonic();self._terminal_message=False
        self._last_observation=None;self._ready_at=None
        self._first_frame=None;self._analysis_message=None;self._user_stop=False
        self.process=self.context.Process(target=capture_loop,
            args=(self.queue,self.stop_event,source,backend,self.preview_queue),
            kwargs={'native_format':native_format, 'model_profile':self._model_profile},daemon=True)
        if self._video_mode:message='正在打开本地视频…'
        elif native_format and backend!=1400:message='正在用摄像头默认格式重试…'
        elif native_format and self.state=='starting':message='正在尝试兼容采集方式…'
        else:message='正在打开摄像头…'
        self.set_state('starting',message)
        try:self.process.start()
        except Exception:
            logging.exception('Could not spawn local vision worker')
            self.process=None;self.close_queue(self.queue);self.close_queue(self.preview_queue)
            self.queue=None;self.preview_queue=None;self.stop_event=None;self._pending_sources.clear()
            self.set_state('error','无法启动识别进程，请重试。');return False
        self.timer.start(30);return True

    def stop(self):
        self._pending_sources.clear();self._user_stop=True
        if self.process is None:
            self.set_state('off','摄像头已关闭');return
        self.stop_event.set();self._stopping_since=time.monotonic()
        self.set_state('stopping','正在关闭摄像头…')

    def _fail_attempt(self,message,now,*,retry=False,force=False):
        self._terminal_message=True
        trying=retry and bool(self._pending_sources)
        logging.warning('Camera attempt ended: %s (retry: %s)',message,trying)
        if trying:
            self.set_state('starting','本次未收到摄像头画面，正在切换采集方式…')
        else:
            self._pending_sources.clear()
            self.set_state('error',message)
        self.stop_event.set()
        self._stopping_since=now-self.STOP_GRACE if force else now

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
                elif kind=='status' and self._first_frame is None:
                    self.set_state('starting',item['text'])
                elif kind=='ready':
                    self._analysis_message=item['text']
                elif kind=='error':
                    self._fail_attempt(item['text'],now,retry=item.get('retry_camera',False))
                elif kind=='ended':
                    self._terminal_message=True
                    self.set_state('off',item['text'])
            for _ in range(6):
                try:item=self.preview_queue.get_nowait()
                except Empty:break
                if self._stopping_since is None and not self._terminal_message:
                    newest=item;self._last_frame=now
            if newest is not None and self._first_frame is None:
                self._first_frame=now
                if not self._analysis_message:
                    self.set_state('previewing','已收到画面，正在加载本地识别模型…')
            if self._first_frame is not None and self._analysis_message and self.state in {'starting','previewing'}:
                self._ready_at=now
                self.set_state('running',self._analysis_message)
            if newest is not None and self.state in {'previewing','running'}:self.frame_ready.emit(newest)
            if observation is not None and self.state=='running':
                self.observation_ready.emit(observation.freshened(now))
            if self._stopping_since is not None and now-self._stopping_since>=self.STOP_GRACE and self.process.is_alive():
                self.process.terminate()
            elif self._stopping_since is None and not self._terminal_message and self.process.is_alive():
                analysis_reference=self._last_observation if self._last_observation is not None else self._ready_at
                startup_limit=self.FIRST_VIDEO_FRAME_TIMEOUT if self._video_mode else self.FIRST_CAMERA_FRAME_TIMEOUT
                if self._first_frame is None and now-self._started_at>=startup_limit:
                    message=('读取视频首帧超时，请另选一个视频。' if self._video_mode else
                             '摄像头未返回首帧。请关闭占用摄像头的应用，重新插拔 USB 设备，再点“开启摄像头”。')
                    self._fail_attempt(message,now,retry=not self._video_mode,force=True)
                elif self._last_frame is not None and now-self._last_frame>12:
                    self._fail_attempt('摄像头画面已中断。请检查连接后重新开启。',now,force=True)
                elif self.state=='previewing' and now-self._first_frame>self.ANALYSIS_START_TIMEOUT:
                    self._fail_attempt('已收到摄像头画面，但识别模型启动超时。请重新开启。',now,force=True)
                elif analysis_reference is not None and now-analysis_reference>8:
                    self._fail_attempt('已有摄像头画面，但本地识别响应超时。请重新开启。',now,force=True)
            if not self.process.is_alive():
                if not self._terminal_message and not self._user_stop:
                    self._fail_attempt('采集进程在返回画面前结束。请检查设备并重试。' if self._first_frame is None else
                                       '识别进程已结束，请重新开启。',now,retry=self._first_frame is None)
                self.process.join(.1);self.process.close();self.process=None
                self.close_queue(self.queue);self.queue=None;self.stop_event=None
                self.close_queue(self.preview_queue);self.preview_queue=None
                self._stopping_since=None
                if self._user_stop:self.set_state('off','摄像头已关闭')
                elif self._terminal_message and self._pending_sources and self.state=='starting':self._open_next()
        if self.scanner is None and self.process is None:self.timer.stop()

    @staticmethod
    def close_queue(queue):
        if queue is not None:queue.cancel_join_thread();queue.close()

    def shutdown(self):
        self.timer.stop()
        self._pending_sources.clear()
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
