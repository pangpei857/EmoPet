"""Spawn-safe sensor entry points; no Qt windows and no audio capture."""
import logging
import os
from queue import Empty, Full
from threading import Thread
import time

from .vision_profiles import DEFAULT_VISION_PROFILE, VISION_PROFILES


def offer(queue,item):
    # Frames are disposable; never allow an inactive preview to build a backlog.
    try:queue.put_nowait(item)
    except Full:
        try:queue.get_nowait()
        except Empty:pass
        try:queue.put_nowait(item)
        except Full:pass


def device_identity(path):
    """Match Windows camera interfaces without guessing from name or index."""
    if not path:
        return None
    value=path.lower().removeprefix('@device:pnp:')
    if value.startswith('\\\\?\\') and '#{' in value:
        return value.rsplit('#{',1)[0]
    return value


def camera_choices(devices):
    choices=[];seen={}
    for device in devices:
        key=device_identity(device.path)
        item=seen.get(key) if key else None
        endpoint=(device.index,device.backend)
        if item is not None:
            if device.backend!=item['backend'] and endpoint not in item['alternatives']:
                item['alternatives'].append(endpoint)
            continue
        item={'index':device.index,'backend':device.backend,'name':device.name,'alternatives':[]}
        choices.append(item)
        if key:seen[key]=item
    return choices


def enumerate_devices(output):
    try:
        import cv2
        from cv2_enumerate_cameras import enumerate_cameras
        devices=[]
        for backend in (cv2.CAP_DSHOW,cv2.CAP_MSMF):
            try:devices.extend(enumerate_cameras(backend))
            except Exception:logging.exception('Could not enumerate camera backend %s',backend)
        output.put({'type':'devices','items':camera_choices(devices)})
    except Exception:
        output.put({'type':'devices','items':[],'error':'设备列表读取失败，可刷新重试。'})


def run_analysis(latest,stop,output,message,model_profile=DEFAULT_VISION_PROFILE):
    engine=None;analysis=None;body=None
    try:
        from .vision import MODEL_DIR, VisionEngine, PhoneDetector
        from .vision_pipeline import ParallelAnalysis
        profile = VISION_PROFILES[model_profile]
        engine=VisionEngine(include_phone=False)
        if stop.is_set():return
        phone=PhoneDetector(MODEL_DIR/profile.detector_file)
        if stop.is_set():return
        if profile.body_model is not None:
            from .body_pose import MEDIAPIPE_POSE_FILE, RTMPOSE_FILE, MediaPipeBody, RTMPoseBody

            estimator, filename = (RTMPoseBody, RTMPOSE_FILE) if profile.body_model == 'rtmpose' else (MediaPipeBody, MEDIAPIPE_POSE_FILE)
            model_path = MODEL_DIR / filename
            if not model_path.is_file():
                raise FileNotFoundError(f'缺少身体姿态模型 {filename}。请使用完整的应用文件夹。')
            body = estimator(model_path)
        if stop.is_set():return
        analysis=ParallelAnalysis(latest,engine,phone,stop,lambda item:offer(output,item),body=body)
        analysis.start()
        offer(output,{'type':'ready','text':f'{message} · {profile.label}'})
        stop.wait()
    except Exception as error:
        logging.exception('Local vision model startup failed')
        if not stop.is_set():
            message = str(error) if isinstance(error, FileNotFoundError) else '已有画面，但所选本地识别方案未能启动。可切换到原版 YOLOv8s 再试。'
            offer(output,{'type':'error','text':message})
        stop.set()
    finally:
        closed=analysis is None or analysis.close()
        if engine is not None and closed:engine.close()
        if body is not None and closed:body.close()


def capture_loop(output,stop,source,backend=700,preview_output=None,*,native_format=False,
                 model_profile=DEFAULT_VISION_PROFILE):
    cap=None;analysis_thread=None;latest=None;first_frame=False
    is_video=isinstance(source,str)
    try:
        if not is_video and backend==1400:
            # This process only handles the camera. Avoid the MSMF hardware
            # transform path while retrying a camera that produced no frames.
            os.environ['OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS']='0'
        import cv2
        from .vision_pipeline import LatestFrames,RateMeter
        previews=output if preview_output is None else preview_output
        cap=cv2.VideoCapture(source) if is_video else cv2.VideoCapture(source,backend)
        if not cap.isOpened():
            raise RuntimeError('无法打开视频文件。' if is_video else '无法打开摄像头。请确认设备已连接、没有被其他应用占用，并允许桌面应用使用摄像头。')
        if not is_video and not native_format:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
            cap.set(cv2.CAP_PROP_FPS,30);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
        if stop.is_set():return
        offer(output,{'type':'status','text':'已打开视频，正在读取画面…' if is_video else '已连接设备，正在等待第一帧画面…'})
        latest=LatestFrames()
        failures=0;frames=0;started=time.monotonic();next_preview=0.;preview_rate=RateMeter()
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
            captured_at=time.monotonic()
            if not ok or bgr is None or not bgr.size:
                if is_video:
                    if not first_frame:raise RuntimeError('无法从视频文件读取画面，请另选一个视频。')
                    offer(output,{'type':'ended','text':'视频播放结束，可重新选择视频或开启摄像头。'});return
                failures+=1
                if failures>=12:
                    if first_frame:raise RuntimeError('摄像头画面中断。请检查连接后重新开启。')
                    raise RuntimeError('摄像头已连接，但没有送出画面。请关闭占用相机的应用，或重新插拔 USB 摄像头。')
                stop.wait(.08);continue
            failures=0
            h,w=bgr.shape[:2]
            if w>960 or h>720:
                factor=min(960/w,720/h);bgr=cv2.resize(bgr,(round(w*factor),round(h*factor)))
            latest.publish(bgr,captured_at)
            # Preview does not wait for any model. Read the camera continuously
            # even when a model is busy, so frames cannot accumulate upstream.
            if captured_at>=next_preview:
                rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
                offer(previews,{'type':'frame','width':rgb.shape[1],'height':rgb.shape[0],
                    'rgb':rgb.tobytes(),'captured_at':captured_at,'preview_fps':preview_rate.tick(captured_at)})
                # Keep a stable deadline instead of comparing with the last
                # frame: Windows timer jitter can otherwise discard every
                # other 30-fps frame at the interval boundary.
                next_preview+=1/30
                if next_preview<=captured_at:next_preview=captured_at+1/30
            if not first_frame:
                first_frame=True
                message='视频测试中' if is_video else '摄像头已开启 · 本地识别就绪'
                analysis_thread=Thread(target=run_analysis,args=(latest,stop,output,message,model_profile),daemon=True)
                analysis_thread.start()
            if is_video:stop.wait(max(0.,frames/fps-(time.monotonic()-started)))
    except Exception as error:
        logging.exception('Local vision worker failed')
        message=str(error) if isinstance(error,(RuntimeError,FileNotFoundError)) else '识别模块启动失败，请检查模型文件与运行依赖，或重新安装完整应用。'
        offer(output,{'type':'error','text':message,'retry_camera':not is_video and not first_frame})
    finally:
        stop.set()
        if cap is not None:cap.release()
        if latest is not None:latest.wake()
        if analysis_thread is not None:analysis_thread.join(1.)
        # Flush short control messages so the supervisor sees the actual error
        # before reaping the worker. Never wait for a backlog of full frames.
        if preview_output is None:output.cancel_join_thread()
        if preview_output is not None:preview_output.cancel_join_thread()
