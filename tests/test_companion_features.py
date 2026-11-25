"""Local end-to-end checks for the study companion's new support features."""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication

from study_pet.audio_sensing import SighCandidate
from study_pet.history import LOCAL_ZONE
from study_pet.perception import FeedbackEvent
from study_pet.storage import Store
from study_pet.ui import Companion, STYLE


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet(STYLE)


class FakeAudioSensing(QObject):
    candidate = Signal(object)
    status_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.update = Mock()
        self.shutdown = Mock()


class FakeSpeech(QObject):
    state_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.busy = False
        self.shutdown = Mock()

    def change_state(self, busy):
        self.busy = busy
        self.state_changed.emit('speaking' if busy else 'idle')


class CompanionFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='momo-companion-features-')
        self.now = 1000.0
        self.wall = datetime(2026, 11, 19, 10, tzinfo=LOCAL_ZONE)
        self.c = Companion(Store(Path(self.temp.name)), tray_enabled=False, music_autostart=False)
        self.c.timer.stop()
        self.c.session.clock = lambda: self.now
        self.c.session.wall_clock = lambda: self.wall
        self.c.history.clock = lambda: self.wall
        self.c.memory.clock = lambda: self.wall
        self.c.reminder_gate.clock = lambda: self.now
        self.c.panel.duration.setValue(5)
        self.c.panel.task.setText('完成基础逻辑题')

    def tearDown(self):
        c = self.c
        c.timer.stop()
        APP.aboutToQuit.disconnect(c.shutdown_audio)
        APP.aboutToQuit.disconnect(c.summary_service.shutdown)
        c.shutdown_vision()
        c.shutdown_chat()
        c.shutdown_audio()
        c.shutdown_music()
        c.summary_service.shutdown()
        for timer in (c.pet.canvas._animation, c.pet.canvas._click_timer,
                      c.pet._bubble_timer, c.pet._mood_timer, c.pet._screen_timer):
            timer.stop()
        for widget in (c.companion_settings, c.camera_panel, c.history_panel, c.chat_panel, c.panel, c.pet):
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.temp.cleanup()

    def advance(self, seconds=1):
        for _ in range(seconds):
            self.now += 1
            self.wall += timedelta(seconds=1)
            self.c.on_tick()

    def test_quiet_away_and_chat_leave_due_support_available_for_recheck(self):
        c = self.c
        c.coach.configure(interval_minutes=1)
        c.set_care_mode('quiet')
        self.assertEqual(c.store.get('companion_mode'), 'quiet')
        c.begin()
        self.advance(60)
        self.assertEqual(c.history.reminders(), [])
        self.assertEqual(c.coach.streak_seconds, 60)

        # Initialize the real camera UI with device discovery stubbed out.
        with patch('study_pet.camera.VisionController.refresh_devices'):
            c.show_camera()
        c.vision_controller.state = 'running'
        c.receive_presence({'state': 'away'})
        c.set_care_mode('balanced')
        self.assertIsNone(c.update_coach())
        self.assertIsNone(c.route_vision_event(FeedbackEvent('care', '要不要歇一下？', 'care')))
        self.assertEqual(c.history.reminders(), [])

        c.receive_presence({'state': 'present'})
        c.show_chat()
        with patch.object(c.chat_panel, 'isActiveWindow', return_value=True):
            self.assertIsNone(c.update_coach())
            self.assertEqual(c.history.reminders(), [])
        with (patch.object(c.chat_panel, 'isActiveWindow', return_value=False),
              patch.object(type(c.chat_panel.client), 'busy', new_callable=PropertyMock, return_value=True)):
            self.assertIsNone(c.update_coach())
            self.assertEqual(c.history.reminders(), [])
        c.chat_panel.hide()
        self.assertEqual(c.update_coach().kind, 'break_due')
        event, = c.history.reminders()
        self.assertEqual((event['source'], event['session_id']), ('coach', c.session.round_id))

    def test_real_feedback_changes_later_rounds_without_learning_from_samples(self):
        c = self.c
        c.coach.configure(global_cooldown_seconds=0, kind_cooldown_seconds=0)
        self.assertTrue(c.memory.set_enabled(True))
        sample = c.send_sample('care')
        self.assertTrue(c.respond_to_reminder(sample, 'thinking'))
        self.assertEqual(c.memory.recent(), [])

        rounds = set()
        care = FeedbackEvent('care', '要不要一起拆解下一步？', 'care')
        for _ in range(3):
            c.begin()
            rounds.add(c.session.round_id)
            identifier = c.route_vision_event(care)
            self.assertIsNotNone(identifier)
            self.assertTrue(c.respond_to_reminder(identifier, 'thinking'))
            c.stop()

        self.assertEqual({event.session_id for event in c.memory.recent()}, rounds)
        self.assertTrue(c.memory.preferences(c.learning_mode())['care'].reduce_interruptions)
        c.begin()
        self.assertIsNone(c.route_vision_event(care))
        self.assertIsNotNone(c.route_vision_event(FeedbackEvent('phone', '正在查资料吗？', 'remind')))
        self.assertTrue(c.memory.set_enabled(False))
        self.assertIsNotNone(c.route_vision_event(care))

    def test_audio_candidates_are_only_used_while_studying_and_speech_is_idle(self):
        c = self.c
        c.set_care_mode('supportive')
        c.update_audio()
        self.assertIsNone(c.audio_sensing)
        with (patch('study_pet.audio_sensing.AudioSensing', FakeAudioSensing),
              patch('study_pet.speech.LocalSpeech', FakeSpeech),
              patch('study_pet.ui.time', SimpleNamespace(monotonic=lambda: self.now))):
            c.set_audio_sensing(True)
            audio = c.audio_sensing
            speech = c.speech_service()
            audio.update.assert_called_with(enabled=True, studying=False, inhibited=False)
            audio.candidate.emit(SighCandidate(self.now, .8))
            self.assertEqual(c.history.reminders(), [])

            c.begin()
            self.advance()
            audio.update.assert_called_with(enabled=True, studying=True, inhibited=False)
            c.toggle()
            self.advance()
            audio.update.assert_called_with(enabled=True, studying=False, inhibited=False)
            audio.candidate.emit(SighCandidate(self.now, .8))
            self.assertEqual(c.history.reminders(), [])

            c.toggle()
            speech.change_state(True)
            audio.update.assert_called_with(enabled=True, studying=True, inhibited=True)
            audio.candidate.emit(SighCandidate(self.now, .8))
            self.assertEqual(c.history.reminders(), [])
            speech.change_state(False)
            audio.update.assert_called_with(enabled=True, studying=True, inhibited=True)
            audio.candidate.emit(SighCandidate(self.now, .8))
            self.assertEqual(c.history.reminders(), [])
            self.advance()
            audio.update.assert_called_with(enabled=True, studying=True, inhibited=False)
            audio.candidate.emit(SighCandidate(self.now, .8))
            event, = c.history.reminders()
            self.assertEqual((event['kind'], event['source'], event['session_id']),
                             ('sigh', 'audio', c.session.round_id))

            c.set_audio_sensing(False)
            audio.update.assert_called_with(enabled=False, studying=True, inhibited=False)


if __name__ == '__main__':
    unittest.main()
