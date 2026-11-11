"""Offline model and spawned-process checks, also runnable in the frozen build."""
from pathlib import Path
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
    frames=[];controller.frame_ready.connect(frames.append)
    with tempfile.TemporaryDirectory(prefix='pet-vision-check-') as directory:
        path=Path(directory)/'fixture.avi'
        image=phone_image if phone_image is not None else np.zeros((480,640,3),dtype=np.uint8)
        image=cv2.resize(image,(640,480))
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),8.,(640,480))
        assert writer.isOpened(),'Video fixture encoder unavailable'
        for _ in range(80):writer.write(image)
        writer.release();panel._video_mode=True
        assert controller.start(str(path))
        deadline=time.monotonic()+35
        while len(frames)<3 and time.monotonic()<deadline and controller.state!='error':QTest.qWait(70)
        assert len(frames)>=3,controller.message
        assert panel.preview.image is not None
        assert panel.policy.phone_duration==0,'Video-test frames must not trigger reminders'
        if preview:
            target=Path(preview);target.parent.mkdir(parents=True,exist_ok=True)
            panel.grab().save(str(target))
        panel.close()
        deadline=time.monotonic()+6
        while controller.process is not None and time.monotonic()<deadline:QTest.qWait(60)
        assert controller.process is None,'Sensor process failed to stop'
        assert panel.preview.image is None,'Stopped preview retained a frame'
        # Invalid devices must fail inside the worker, with the GUI still alive.
        panel._video_mode=False;assert controller.start(99,700)
        deadline=time.monotonic()+15
        while controller.state not in {'error','off'} and time.monotonic()<deadline:QTest.qWait(70)
        assert controller.state=='error','Missing camera did not report an error'
        controller.shutdown()
    print('PASS: offline models, phone fixtures, spawned video inference, close/release, invalid-camera recovery',flush=True)
    print('VISION_FIXTURE_RESULTS',results,flush=True)
