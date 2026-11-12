"""Offline model and spawned-process checks, also runnable in the frozen build."""
from pathlib import Path
import json
import statistics
import tempfile
import time


def run(companion,preview=None,fixtures=None):
    import cv2
    import numpy as np
    from PySide6.QtTest import QTest
    from .vision import VisionEngine

    results=[];portrait=None;phone_image=None
    with VisionEngine() as engine:
        rgb,empty=engine.analyze(np.zeros((480,640,3),dtype=np.uint8))
        assert not empty.phones and not empty.faces
        if fixtures:
            fixtures=Path(fixtures)
            path=fixtures/'portrait.jpg'
            portrait=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            assert portrait is not None
            _,face=engine.analyze(portrait)
            assert len(face.faces)==1,'Portrait fixture face was not detected'
            for path in sorted(fixtures.glob('000*.jpg')):
                bgr=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
                # A new engine uses video timestamps; unrelated fixtures are
                # spaced apart, so landmark tracking falls back to detection.
                _,observation=engine.analyze(bgr)
                results.append({'sample':path.name,'phones':len(observation.phones),'hands':len(observation.hands),
                    'faces':len(observation.faces),'near_hand':observation.phone_near_hand,'ms':round(observation.inference_ms)})
                if observation.phones and phone_image is None:phone_image=bgr
            assert phone_image is not None,'No COCO phone fixture was detected'
    companion.show_camera();panel=companion.camera_panel;controller=companion.vision_controller
    # This check explicitly enters video-test mode: no automatic pet feedback.
    frames=[];observations=[];frame_times=[];result_times=[]
    def receive_frame(item):frames.append(item);frame_times.append(time.monotonic())
    def receive_observation(item):observations.append(item);result_times.append(time.monotonic())
    controller.frame_ready.connect(receive_frame);controller.observation_ready.connect(receive_observation)
    with tempfile.TemporaryDirectory(prefix='pet-vision-check-') as directory:
        path=Path(directory)/'fixture.avi'
        image=portrait if portrait is not None else phone_image if phone_image is not None else np.zeros((480,640,3),dtype=np.uint8)
        image=cv2.resize(image,(640,480))
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),30.,(640,480))
        assert writer.isOpened(),'Video fixture encoder unavailable'
        for _ in range(300):writer.write(image)
        writer.release();panel._video_mode=True
        try:
            assert controller.start(str(path))
            deadline=time.monotonic()+35
            while (len(frames)<60 or len(observations)<15 or not any(o.phone_timestamp is not None for o in observations)) and time.monotonic()<deadline and controller.state!='error':QTest.qWait(10)
            intervals=[(b-a)*1000 for a,b in zip(frame_times[5:],frame_times[6:])]
            phone_times=[o.phone_ms for o in observations if o.phone_ms>0]
            metrics={'preview_frames':len(frames),'observations':len(observations),
                'capture_preview_hz':round(frames[-1].get('preview_fps',0.),1) if frames else 0,
                'preview_hz':round(1000/statistics.median(intervals),1) if intervals else 0,
                'median_preview_ms':round(statistics.median(intervals),1) if intervals else None,
                'median_phone_ms':round(statistics.median(phone_times),1) if phone_times else None,
                'median_face_age_ms':round(statistics.median((t-o.timestamp)*1000 for t,o in zip(result_times,observations)),1) if observations else None}
            if observations:
                metrics.update(face_hz=round(observations[-1].face_fps,1),phone_hz=round(observations[-1].phone_fps,1))
            if preview:
                target=Path(preview);target.parent.mkdir(parents=True,exist_ok=True)
                panel.grab().save(str(target))
                target.with_suffix('.json').write_text(json.dumps({'pipeline':metrics,'fixtures':results},indent=2),encoding='utf-8')
            assert len(frames)>=60,controller.message
            assert len(observations)>=15,'Independent feature analysis did not publish results'
            assert phone_times,'Independent phone analysis did not publish results'
            if portrait is not None:assert any(len(o.faces)==1 and o.face_fresh for o in observations),'Async face tracking failed'
            # Compare against the actual expensive model, not the arbitrary
            # face-worker rate: a 15 Hz preview and 15 Hz face worker may be
            # independent even though their frame counts are identical.
            assert statistics.median(intervals)<max(70.,statistics.median(phone_times)*.9),metrics
            assert panel.preview.image is not None
            assert panel.policy.phone_duration==0,'Video-test frames must not trigger reminders'
            panel.close()
            deadline=time.monotonic()+6
            while controller.process is not None and time.monotonic()<deadline:QTest.qWait(30)
            assert controller.process is None,'Sensor process failed to stop'
            assert panel.preview.image is None,'Stopped preview retained a frame'
            # Invalid devices must fail inside the worker, with the GUI still alive.
            panel._video_mode=False;assert controller.start(99,700)
            deadline=time.monotonic()+15
            while controller.state not in {'error','off'} and time.monotonic()<deadline:QTest.qWait(30)
            assert controller.state=='error','Missing camera did not report an error'
        finally:controller.shutdown()
    print('PASS: offline models, phone fixtures, independent preview/face/phone, close/release, invalid-camera recovery',flush=True)
    print('PIPELINE_RESULTS',metrics,flush=True)
    print('VISION_FIXTURE_RESULTS',results,flush=True)
