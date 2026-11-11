"""Spawn-safe sensor entry points; no Qt windows and no audio capture."""
import logging
from queue import Empty, Full
import time


def offer(queue,item):
    # Frames are disposable; never allow an inactive preview to build a backlog.
    try:queue.put_nowait(item)
    except Full:
        try:queue.get_nowait()
        except Empty:pass
        try:queue.put_nowait(item)
        except Full:pass


def enumerate_devices(output):
    try:
        import cv2
        from cv2_enumerate_cameras import enumerate_cameras
        devices=enumerate_cameras(cv2.CAP_DSHOW)
        if not devices:devices=enumerate_cameras(cv2.CAP_MSMF)
        output.put({'type':'devices','items':[{'index':d.index,'backend':d.backend,'name':d.name} for d in devices]})
    except Exception:
        output.put({'type':'devices','items':[],'error':'设备列表读取失败，可刷新重试。'})


def capture_loop(output,stop,source,backend=700):
    cap=None;engine=None
    try:
        import cv2
        from .vision import VisionEngine
        is_video=isinstance(source,str)
        cap=cv2.VideoCapture(source) if is_video else cv2.VideoCapture(source,backend)
        if not cap.isOpened():
            raise RuntimeError('无法打开视频文件。' if is_video else '无法打开摄像头。请确认设备已连接、没有被其他应用占用，并允许桌面应用使用摄像头。')
        if not is_video:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
            cap.set(cv2.CAP_PROP_FPS,15);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
        if stop.is_set():return
        offer(output,{'type':'status','text':'正在加载本地识别模型…'})
        engine=VisionEngine()
        if stop.is_set():return
        offer(output,{'type':'ready','text':'视频测试中' if is_video else '摄像头已开启'})
        failures=0;frames=0;started=time.monotonic()
        fps=cap.get(cv2.CAP_PROP_FPS) if is_video else 0
        if not 1<=fps<=240:fps=25
        while not stop.is_set():
            tick=time.monotonic()
            if is_video:
                # Follow playback time instead of slowing 30 fps clips to the
                # analysis rate. Camera observations remain wall-clock based.
                target=int((tick-started)*fps)
                while frames<target and not stop.is_set():
                    if not cap.grab():break
                    frames+=1
            ok,bgr=cap.read();frames+=1
            if not ok:
                if is_video:
                    offer(output,{'type':'ended','text':'视频播放结束，可重新选择视频或开启摄像头。'});return
                failures+=1
                if failures>=6:raise RuntimeError('摄像头画面中断。请检查连接后重新开启。')
                stop.wait(.08);continue
            failures=0
            h,w=bgr.shape[:2]
            if w>960 or h>720:
                factor=min(960/w,720/h);bgr=cv2.resize(bgr,(round(w*factor),round(h*factor)))
            rgb,observation=engine.analyze(bgr,time.monotonic())
            if stop.is_set():break
            offer(output,{'type':'frame','width':rgb.shape[1],'height':rgb.shape[0],
                          'rgb':rgb.tobytes(),'observation':observation})
            stop.wait(max(0.,.125-(time.monotonic()-tick)))
    except Exception as error:
        logging.exception('Local vision worker failed')
        message=str(error) if isinstance(error,(RuntimeError,FileNotFoundError)) else '识别模块启动失败，请检查模型文件与运行依赖，或重新安装完整应用。'
        offer(output,{'type':'error','text':message})
    finally:
        if cap is not None:cap.release()
        if engine is not None:engine.close()
        output.cancel_join_thread()
