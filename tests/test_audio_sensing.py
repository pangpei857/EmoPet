from queue import Queue
from threading import Event
import time
import unittest

import numpy as np
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from study_pet.audio_sensing import AudioSensing, SighCandidate, SighGate, YAMNet, usable_signal


APP = QApplication.instance() or QApplication([])


class SighGateTests(unittest.TestCase):
    def test_competing_speech_resets_confirmation_and_sustained_event_fires_once(self):
        gate = SighGate()
        positive = {'Sigh': 0.72, 'Breathing': 0.22}
        self.assertIsNone(gate.observe(positive, 1))
        self.assertIsNone(gate.observe({'Sigh': 0.72, 'Speech': 0.68}, 1.5))
        self.assertIsNone(gate.observe(positive, 2))
        self.assertEqual(gate.observe({'Sigh': 0.60}, 2.5), SighCandidate(2.5, 0.60))
        self.assertIsNone(gate.observe(positive, 3))
        gate.interrupt()
        self.assertIsNone(gate.observe(positive, 4))
        self.assertIsNone(gate.observe(positive, 4.5))
        gate.interrupt()
        self.assertIsNone(gate.observe(positive, 18))
        self.assertEqual(gate.observe(positive, 18.5), SighCandidate(18.5, 0.72))

    def test_quality_and_discontinuity_reject_unreliable_windows(self):
        self.assertFalse(usable_signal(np.zeros(100)))
        self.assertFalse(usable_signal(np.full(100, 0.02)))
        self.assertFalse(usable_signal(np.tile([-1.0, 1.0], 50)))
        self.assertFalse(usable_signal(np.array([0.5, float('nan')])))
        self.assertTrue(usable_signal(np.sin(np.linspace(0, 10, 200)) * 0.1))
        gate = SighGate()
        self.assertIsNone(gate.observe({'Sigh': 0.7}, 1))
        self.assertIsNone(gate.observe({'Sigh': 0.7}, 3))
        self.assertEqual(gate.observe({'Sigh': 0.7}, 3.5), SighCandidate(3.5, 0.7))

    def test_shipped_model_returns_sigh_label_and_rejects_silence(self):
        model = YAMNet()
        self.addCleanup(model.close)
        for rate in (16000, 44100):
            scores = model.scores(np.zeros(round(0.975 * rate), dtype=np.float32), rate)
            self.assertIn('Sigh', scores)
            self.assertGreater(scores['Silence'], scores['Sigh'])
            self.assertIsNone(SighGate().observe(scores, 0))


class AudioSensingTests(unittest.TestCase):
    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), 'Timed out waiting for audio worker state')

    def test_worker_requires_consent_and_study_and_discards_results_on_inhibit(self):
        started = Queue()
        stopped = Queue()

        def listener(stop, report):
            report('listening')
            started.put((stop, report))
            stop.wait(2)
            stopped.put(True)

        controller = AudioSensing(listener=listener)
        self.addCleanup(controller.shutdown)
        heard = []
        controller.candidate.connect(heard.append)
        controller.update(enabled=False, studying=True)
        controller.update(enabled=True, studying=False)
        self.assertTrue(started.empty())
        controller.update(enabled=True, studying=True)
        self.wait_for(lambda: not started.empty())
        first_stop, report = started.get_nowait()
        report('candidate', SighCandidate(time.monotonic() - 3, 0.75))
        report('candidate', SighCandidate(time.monotonic(), 0.75))
        self.wait_for(lambda: len(heard) == 1)
        report('candidate', SighCandidate(time.monotonic(), 0.80))
        controller.update(enabled=True, studying=True, inhibited=True)
        self.assertTrue(first_stop.is_set())
        self.wait_for(lambda: not stopped.empty())
        self.assertEqual(len(heard), 1)
        controller.update(enabled=True, studying=True, inhibited=False)
        self.wait_for(lambda: not started.empty())
        new_stop, _ = started.get_nowait()
        self.assertIsNot(first_stop, new_stop)
        controller.shutdown()
        self.assertTrue(new_stop.is_set())

    def test_worker_error_waits_for_explicit_retry(self):
        calls = Queue()
        fail = Event()

        def listener(stop, report):
            calls.put(True)
            if fail.wait(1):
                report('error', '模拟麦克风错误')

        controller = AudioSensing(listener=listener)
        self.addCleanup(controller.shutdown)
        controller.update(enabled=True, studying=True)
        self.wait_for(lambda: calls.qsize() == 1)
        fail.set()
        self.wait_for(lambda: controller.status == '模拟麦克风错误')
        controller.update(enabled=True, studying=True)
        QTest.qWait(20)
        self.assertEqual(calls.qsize(), 1)
        controller.update(enabled=False, studying=True)
        controller.update(enabled=True, studying=True)
        self.wait_for(lambda: calls.qsize() == 2)
