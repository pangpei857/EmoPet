"""End-to-end local coaching flows with a fake clock and temporary profile."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from study_pet.focus import Status
from study_pet.history import LOCAL_ZONE, stamp
from study_pet.perception import Box, FeedbackEvent, Observation
from study_pet.storage import Store
from study_pet.ui import Companion, STYLE


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet(STYLE)


class CoachUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='momo-coach-ui-')
        self.now = 1000.0
        self.wall = datetime(2026, 11, 17, 10, tzinfo=LOCAL_ZONE)
        self.c = Companion(Store(Path(self.temp.name)), tray_enabled=False, music_autostart=False)
        self.c.timer.stop()
        self.c.session.clock = lambda: self.now
        self.c.session.wall_clock = lambda: self.wall
        self.c.history.clock = lambda: self.wall
        self.c.reminder_gate.clock = lambda: self.now
        self.c.panel.duration.setValue(5)
        self.c.panel.task.setText('完成状态转移练习')

    def tearDown(self):
        c = self.c
        c.timer.stop()
        c.shutdown_vision()
        c.shutdown_chat()
        c.shutdown_music()
        c.summary_service.shutdown()
        for timer in (c.pet.canvas._animation, c.pet.canvas._click_timer,
                      c.pet._bubble_timer, c.pet._mood_timer, c.pet._screen_timer):
            timer.stop()
        for widget in (c.camera_panel, c.history_panel, c.chat_panel, c.panel, c.pet):
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.temp.cleanup()

    def advance(self, seconds):
        # Repeated small samples exercise the live timer, not sleep backfilling.
        for _ in range(seconds):
            self.now += 1
            self.wall += timedelta(seconds=1)
            self.c.on_tick()

    def coach_reminders(self):
        return [event for event in self.c.history.reminders() if event['source'] == 'coach']

    def simulated_camera(self):
        with patch('study_pet.camera.VisionController.refresh_devices'):
            self.c.show_camera()
        camera = self.c.camera_panel
        camera.controller.state = 'running'
        camera.phone_duration.setValue(3)
        camera.behaviors.wall_anchor = self.wall
        camera.behaviors.mono_anchor = self.now
        return camera

    def feed_phone(self, camera, seconds, positive=True):
        for _ in range(seconds * 4):
            self.now += .25
            self.wall += timedelta(seconds=.25)
            self.c.on_tick()
            camera.on_observation(Observation(
                self.now,
                phones=(Box(.4, .4, .6, .8),) if positive else (),
                hands=(tuple((.5, .6) for _ in range(8)),) if positive else (),
                faces=(Box(.2, .1, .4, .3),),
            ))

    def phone_reminders(self):
        return [event for event in self.c.history.reminders()
                if event['source'] == 'vision' and event['kind'] == 'phone']

    def test_mid_round_break_preserves_identity_remaining_and_learning_time(self):
        self.c.begin()
        focus = self.c.session
        identifier = focus.round_id
        self.advance(23)
        self.c.panel.rest.click()
        self.assertIs(self.c._suspended_focus, focus)
        self.assertEqual(focus.status, Status.PAUSED)
        self.assertEqual(focus.remaining, 277)
        self.assertEqual(self.c.session.kind, 'break')
        self.assertNotEqual(self.c.session.round_id, identifier)
        self.assertEqual(self.c.history.session(identifier)['elapsed'], 23)

        self.advance(300)
        self.assertEqual(self.c.session.status, Status.COMPLETED)
        self.assertIs(self.c._suspended_focus, focus)
        self.assertEqual(self.c.history.summary()['seconds'], 23)
        self.assertEqual(self.c.history.summary()['completed'], 0)
        self.assertEqual(self.c.coach.streak_seconds, 0)

        self.c.panel.start.click()
        self.assertIs(self.c.session, focus)
        self.assertIsNone(self.c._suspended_focus)
        self.assertEqual((focus.round_id, focus.remaining, focus.status),
                         (identifier, 277, Status.RUNNING))
        self.assertEqual(self.c.history.session(identifier)['status'], 'running')
        self.advance(7)
        self.c.stop()
        self.assertEqual(self.c.history.session(identifier)['elapsed'], 30)
        self.assertEqual(self.c.history.summary()['seconds'], 30)

    def test_ending_break_early_leaves_original_task_paused(self):
        self.c.begin()
        identifier = self.c.session.round_id
        self.advance(12)
        self.c.panel.rest.click()
        self.advance(25)
        self.c.panel.stop.click()
        self.assertEqual(self.c.session.kind, 'focus')
        self.assertEqual(self.c.session.round_id, identifier)
        self.assertEqual(self.c.session.status, Status.PAUSED)
        self.assertEqual(self.c.session.remaining, 288)
        self.assertIsNone(self.c._suspended_focus)
        self.assertEqual(self.c.history.session(identifier)['elapsed'], 12)
        self.assertEqual(self.c.coach.streak_seconds, 12)
        self.c.panel.start.click()
        self.advance(3)
        self.c.stop()
        self.assertEqual(self.c.history.summary()['seconds'], 15)

    def test_rest_cannot_nest_and_preserves_already_paused_task(self):
        self.c.begin()
        focus = self.c.session
        self.advance(10)
        self.c.toggle()
        self.assertEqual(focus.pause_count, 1)
        self.c.rest()
        rest_id = self.c.session.round_id
        self.c.rest()
        self.assertEqual(self.c.session.round_id, rest_id)
        self.assertEqual(focus.pause_count, 1)
        self.c.stop()
        self.assertIs(self.c.session, focus)
        self.assertEqual(focus.status, Status.PAUSED)
        self.assertEqual(len(self.c.history.sessions()), 2)

    def test_cross_round_reminder_buttons_start_rest_for_current_round(self):
        self.c.coach.configure(interval_minutes=1)
        self.c.begin()
        self.advance(40)
        self.c.stop()
        self.c.begin()
        focus = self.c.session
        self.advance(20)
        events = self.coach_reminders()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'break_due')
        self.assertEqual(events[0]['session_id'], focus.round_id)
        bubble = self.c.pet.bubble
        self.assertEqual(bubble.reminder_kind, 'break_due')
        self.assertTrue(bubble.action_buttons['rest_now'].isVisible())
        self.assertTrue(bubble.action_buttons['later'].isVisible())
        self.assertFalse(bubble.action_buttons['research'].isVisible())
        bubble.action_buttons['rest_now'].click()
        self.assertEqual(self.c.history.reminder(events[0]['id'])['response'], 'rest_now')
        self.assertEqual(self.c.session.kind, 'break')
        self.assertIs(self.c._suspended_focus, focus)
        self.assertEqual(focus.remaining, 280)

    def test_later_button_keeps_task_and_reasks_after_ten_minutes(self):
        self.c.panel.duration.setValue(120)
        self.c.coach.configure(interval_minutes=1)
        self.c.begin()
        focus_id = self.c.session.round_id
        self.advance(60)
        first = self.coach_reminders()[0]
        self.c.pet.bubble.action_buttons['later'].click()
        self.assertEqual(self.c.history.reminder(first['id'])['response'], 'later')
        self.assertEqual(self.c.session.round_id, focus_id)
        self.assertEqual(self.c.session.status, Status.RUNNING)
        self.advance(599)
        self.assertEqual(len(self.coach_reminders()), 1)
        self.advance(1)
        self.assertEqual(len(self.coach_reminders()), 2)
        self.assertEqual(self.c.pet.bubble.reminder_kind, 'break_due')

    def test_hidden_pet_and_disabled_bubbles_do_not_consume_due_reminder(self):
        self.c.coach.configure(interval_minutes=1)
        self.c.begin()
        self.c.pet.hide()
        self.advance(60)
        self.assertEqual(self.coach_reminders(), [])
        self.assertEqual(self.c.coach.streak_seconds, 60)
        self.c.pet.set_bubbles_enabled(False)
        self.c.show_pet()
        self.c.update_coach()
        self.assertEqual(self.coach_reminders(), [])
        self.c.pet.set_bubbles_enabled(True)
        event = self.c.update_coach()
        self.assertEqual(event.kind, 'break_due')
        self.assertEqual(len(self.coach_reminders()), 1)

    def test_ui_master_switch_persists_and_does_not_consume_due_reminder(self):
        self.c.panel.duration.setValue(120)
        self.c.panel.care_interval.setValue(15)
        self.c.panel.care_enabled.setChecked(False)
        self.assertFalse(self.c.store.get('proactive')['enabled'])
        self.assertEqual(self.c.store.get('proactive')['interval_minutes'], 15)
        self.c.begin()
        self.advance(900)
        self.assertEqual(self.coach_reminders(), [])
        self.assertEqual(self.c.coach.streak_seconds, 900)
        self.c.panel.care_enabled.setChecked(True)
        self.assertTrue(self.c.store.get('proactive')['enabled'])
        self.assertEqual(self.c.update_coach().kind, 'break_due')
        self.assertEqual(len(self.coach_reminders()), 1)

    def test_help_opens_composer_without_sending_a_network_request(self):
        self.c.begin()
        event_id = self.c.receive_vision_event(FeedbackEvent('care', '需要我帮忙吗？', 'care'))
        self.assertTrue(self.c.pet.bubble.action_buttons['help'].isVisible())
        with patch('study_pet.chat_network.ChatClient.start') as network_start:
            self.c.pet.bubble.action_buttons['help'].click()
            self.assertIsNotNone(self.c.chat_panel)
            self.assertTrue(self.c.chat_panel.isVisible())
            text = self.c.chat_panel.composer.toPlainText()
            self.assertIn('完成状态转移练习', text)
            self.assertIn('卡在哪里', text)
            self.assertEqual(self.c.chat_panel.chats.conversations(), [])
            network_start.assert_not_called()
        self.assertEqual(self.c.history.reminder(event_id)['response'], 'help')

    def test_old_break_reminder_cannot_interrupt_a_new_round(self):
        self.c.coach.configure(interval_minutes=1)
        self.c.begin()
        self.advance(60)
        old = self.coach_reminders()[0]
        self.c.stop()
        self.c.begin()
        identifier = self.c.session.round_id
        self.assertFalse(self.c.respond_to_reminder(old['id'], 'rest_now'))
        self.assertEqual(self.c.session.round_id, identifier)
        self.assertEqual(self.c.session.kind, 'focus')
        self.assertIsNone(self.c._suspended_focus)

    def test_rest_at_deadline_does_not_suspend_a_completed_task(self):
        self.c.panel.duration.setValue(1)
        self.c.begin()
        focus_id = self.c.session.round_id
        self.now += 59.9
        self.wall += timedelta(seconds=59.9)

        def flush_crosses_deadline():
            # Camera flush/SQLite can consume the final fraction of a second.
            self.now += .2
            self.wall += timedelta(seconds=.2)

        with patch.object(self.c, 'flush_vision_behaviors', side_effect=flush_crosses_deadline):
            self.c.rest()
        self.assertEqual(self.c.session.kind, 'break')
        self.assertIsNone(self.c._suspended_focus)
        self.assertEqual(self.c.history.session(focus_id)['status'], 'completed')
        self.assertEqual(self.c.history.summary()['completed'], 1)
        self.assertEqual(self.c.history.summary()['seconds'], 60)

    def test_natural_completion_flushes_final_behavior_before_summary(self):
        self.c.panel.duration.setValue(1)
        self.c.begin()
        identifier = self.c.session.round_id
        start = self.wall
        ongoing = {'id': 'final-presence', 'type': 'presence',
                   'started_at': stamp(start),
                   'ended_at': stamp(start + timedelta(seconds=55)),
                   'duration': 55, 'evidence': {}, 'status': 'ongoing'}
        self.c.receive_behavior(ongoing)
        closed = {**ongoing, 'ended_at': stamp(start + timedelta(seconds=60)),
                  'duration': 60, 'status': 'closed'}
        camera = SimpleNamespace(
            flush_behaviors=lambda: self.c.receive_behavior(closed),
            reset_behaviors=lambda: None,
            policy=SimpleNamespace(reset_evidence=lambda: None),
        )
        self.c.camera_panel = camera
        try:
            self.now += 60
            self.wall += timedelta(seconds=60)
            self.c.on_tick()
            event = self.c.history.behaviors(session_id=identifier)[0]
            self.assertEqual((event['status'], event['duration']), ('closed', 60))
            summary = self.c.history.learning_summary('session', identifier)
            self.assertEqual(summary['facts']['visual']['presence'], 60)
            # Only the explicit synchronous final flush can write after completion.
            late = {**closed, 'id': 'late-unrelated-event'}
            self.assertIsNone(self.c.receive_behavior(late))
            self.assertEqual(len(self.c.history.behaviors(session_id=identifier)), 1)
        finally:
            self.c.camera_panel = None

    def test_visual_candidate_rejected_by_master_switch_can_retry_same_episode(self):
        self.c.begin()
        camera = self.simulated_camera()
        self.c.panel.care_enabled.setChecked(False)
        self.feed_phone(camera, 5)
        self.assertEqual(self.phone_reminders(), [])
        segments = [event for event in self.c.history.behaviors(session_id=self.c.session.round_id)
                    if event['kind'] == 'phone']
        self.assertEqual(len(segments), 1)
        self.assertGreaterEqual(segments[0]['duration'], 3)
        event_id = segments[0]['id']
        self.assertNotIn(event_id, camera._announced)

        self.c.panel.care_enabled.setChecked(True)
        self.feed_phone(camera, 3)
        reminders = self.phone_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]['behavior_id'], event_id)
        self.assertIn(event_id, camera._announced)
        self.feed_phone(camera, 5)
        self.assertEqual(len(self.phone_reminders()), 1)

    def test_visual_candidate_retries_after_global_cooldown_without_new_episode(self):
        self.c.begin()
        camera = self.simulated_camera()
        self.c.route_vision_event(FeedbackEvent('care', '先前的关怀。', 'care'))
        self.feed_phone(camera, 5)
        event_id = camera.behaviors.event_id('phone')
        self.assertIsNotNone(event_id)
        self.assertEqual(self.phone_reminders(), [])
        self.assertNotIn(event_id, camera._announced)
        self.feed_phone(camera, 84)
        self.assertEqual(self.phone_reminders(), [])
        self.feed_phone(camera, 4)
        reminders = self.phone_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]['behavior_id'], event_id)

    def test_rejected_visual_candidate_is_not_replayed_after_behavior_ends(self):
        self.c.begin()
        camera = self.simulated_camera()
        self.c.route_vision_event(FeedbackEvent('care', '先前的关怀。', 'care'))
        self.feed_phone(camera, 5)
        self.assertEqual(self.phone_reminders(), [])
        self.feed_phone(camera, 90, positive=False)
        self.assertEqual(self.phone_reminders(), [])


if __name__ == '__main__':
    unittest.main()
