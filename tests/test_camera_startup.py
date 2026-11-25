from queue import Queue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtWidgets import QApplication

from study_pet.camera import VisionController
from study_pet.vision_worker import camera_choices, capture_loop


APP = QApplication.instance() or QApplication([])


class LocalQueue(Queue):
    def cancel_join_thread(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self, *, args, kwargs, **other):
        self.endpoint = args[2:4]
        self.native_format = kwargs['native_format']
        self.alive = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False

    def join(self, timeout):
        pass

    def close(self):
        pass


class CameraStartupTests(unittest.TestCase):
    def setUp(self):
        self.controller = VisionController()
        self.controller.context = SimpleNamespace(Queue=LocalQueue, Event=Event, Process=FakeProcess)
        self.now = 100.
        clock = patch('study_pet.camera.time.monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.addCleanup(self.controller.shutdown)
        self.frame = {'type': 'frame', 'width': 2, 'height': 2, 'rgb': bytes(12)}

    def test_profile_opens_only_after_first_frame_even_if_models_claim_ready(self):
        c = self.controller
        c.start(0, 700)
        c.queue.put({'type': 'ready', 'text': '识别就绪'})
        c.poll()
        self.assertEqual(c.state, 'starting')
        frames = []
        c.frame_ready.connect(frames.append)
        c.preview_queue.put(self.frame)
        c.poll()
        self.assertEqual(c.state, 'running')
        self.assertEqual(frames, [self.frame])

    def test_first_frame_displays_while_analysis_is_loading(self):
        c = self.controller
        frames = []
        c.frame_ready.connect(frames.append)
        c.start(3, 700)
        c.preview_queue.put(self.frame)
        c.poll()
        self.assertEqual(c.state, 'previewing')
        self.assertTrue(c.active)
        self.assertEqual(frames, [self.frame])
        c.queue.put({'type': 'ready', 'text': '识别就绪'})
        c.poll()
        self.assertEqual(c.state, 'running')

    def test_stalled_camera_falls_back_after_releasing_original_worker(self):
        c = self.controller
        c.start(1, 700, alternatives=[(4, 1400)])
        original = c.process
        self.now += c.FIRST_CAMERA_FRAME_TIMEOUT + 1
        c.poll()
        self.assertEqual(c.state, 'starting')
        c.poll()
        self.assertFalse(original.alive)
        self.assertEqual(c.process.endpoint, (4, 1400))
        self.assertTrue(c.process.native_format)
        self.now += c.FIRST_CAMERA_FRAME_TIMEOUT + 1
        c.poll()
        c.poll()
        self.assertEqual(c.state, 'error')
        self.assertIn('首帧', c.message)
        self.assertIsNone(c.process)

    def test_stop_cancels_the_pending_fallback(self):
        c = self.controller
        c.start(1, 700, alternatives=[(4, 1400)])
        self.now += c.FIRST_CAMERA_FRAME_TIMEOUT + 1
        c.poll()
        c.stop()
        self.now += c.STOP_GRACE + 1
        c.poll()
        self.assertEqual(c.state, 'off')
        self.assertIsNone(c.process)

    def test_matching_camera_paths_does_not_mix_identical_names(self):
        def device(index, backend, instance, interface):
            return SimpleNamespace(index=index, backend=backend, name='USB Camera',
                path='\\\\?\\usb#vid_1234&pid_5678#'+instance+'#{'+interface+'}\\global')

        choices = camera_choices([
            device(0, 700, 'A', 'one'), device(1, 700, 'B', 'one'),
            device(7, 1400, 'B', 'two'), device(4, 1400, 'A', 'two'),
        ])
        self.assertEqual([item['alternatives'] for item in choices], [[(4, 1400)], [(7, 1400)]])

    def test_hd_capture_keeps_original_pixels_for_sliced_detection(self):
        original = np.zeros((960, 1280, 3), dtype=np.uint8)
        for profile in ('yolov8s', 'yolo26_rtmpose'):
            with self.subTest(profile=profile):
                cap = Mock()
                cap.get.return_value = 30.
                cap.read.side_effect = ((True, original), (False, None))
                output, previews, stop = LocalQueue(), LocalQueue(), Event()
                with (patch('cv2.VideoCapture', return_value=cap),
                      patch('study_pet.vision_worker.Thread') as analysis):
                    capture_loop(output, stop, 'fixture.avi', preview_output=previews, model_profile=profile)

                latest = analysis.call_args.kwargs['args'][0].frame
                self.assertEqual(latest.image.shape, (720, 960, 3))
                self.assertIs(latest.original_image, original if profile == 'yolo26_rtmpose' else None)
                preview = previews.get_nowait()
                self.assertEqual((preview['width'], preview['height']), (960, 720))
                cap.release.assert_called_once()
