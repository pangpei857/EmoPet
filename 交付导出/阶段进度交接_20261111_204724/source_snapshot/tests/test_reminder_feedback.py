from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from study_pet.ui import Companion,STYLE
from study_pet.storage import Store
from study_pet.history import LOCAL_ZONE
from study_pet.perception import FeedbackEvent,ReminderGate,ReminderPolicy,VisionSettings,Box,Observation

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False);APP.setStyleSheet(STYLE)


class ReminderFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pet-response-')
        self.now=1000.;self.wall=datetime(2026,11,11,10,tzinfo=LOCAL_ZONE)
        self.c=Companion(Store(Path(self.temp.name)),tray_enabled=False)
        self.c.session.clock=lambda:self.now;self.c.session.wall_clock=lambda:self.wall
        self.c.history.clock=lambda:self.wall;self.c.reminder_gate.clock=lambda:self.now
        self.c.panel.duration.setValue(1)

    def tearDown(self):
        c=self.c;c.timer.stop();c.pet.hide();c.panel.hide()
        c.shutdown_vision()
        if c.camera_panel is not None:c.camera_panel.hide();c.camera_panel.deleteLater()
        if c.history_panel is not None:c.history_panel.hide();c.history_panel.deleteLater()
        c.pet.deleteLater();c.panel.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents();self.temp.cleanup()

    def advance(self,seconds):self.now+=seconds;self.wall+=timedelta(seconds=seconds)

    def event(self,kind='phone'):
        return self.c.receive_vision_event(FeedbackEvent(kind,'测试提醒，试着回应一下。','remind' if kind=='phone' else 'care'))

    def test_research_button_saves_once_and_only_pauses_phone(self):
        self.c.begin();identifier=self.event()
        button=self.c.pet.bubble.action_buttons['research']
        self.assertTrue(button.isVisible());QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        self.assertEqual(self.c.history.reminder(identifier)['response'],'research')
        self.assertTrue(self.c.reminder_gate.phone_paused);self.assertFalse(self.c.reminder_gate.care_paused)
        self.assertFalse(self.c.reminder_gate.snoozed)
        self.assertFalse(self.c.respond_to_reminder(identifier,'snooze'))
        self.advance(301);self.assertFalse(self.c.reminder_gate.phone_paused)

    def test_false_positive_and_snooze_preserve_feature_settings(self):
        self.c.begin();identifier=self.event('care')
        self.assertFalse(self.c.pet.bubble.action_buttons['research'].isVisible())
        QTest.mouseClick(self.c.pet.bubble.action_buttons['false_positive'],Qt.MouseButton.LeftButton)
        self.assertTrue(self.c.reminder_gate.care_paused);self.assertFalse(self.c.reminder_gate.phone_paused)
        self.assertEqual(self.c.history.summary()['corrections'],1)
        identifier=self.event();self.c.respond_to_reminder(identifier,'snooze')
        self.assertTrue(self.c.reminder_gate.snoozed)
        self.advance(601);self.assertFalse(self.c.reminder_gate.snoozed)

    def test_example_feedback_does_not_change_real_counts_or_gate(self):
        self.c.begin();identifier=self.c.send_sample('phone')
        self.c.respond_to_reminder(identifier,'research')
        self.assertEqual(self.c.history.summary()['reminders'],0)
        self.assertFalse(self.c.reminder_gate.phone_paused)
        self.assertEqual(self.c.history.reminder(identifier)['source'],'example')
        self.assertIsNone(self.c.history.reminder(identifier)['session_id'])
        self.c.show_history();self.c.history_panel.reveal_reminder(identifier)
        self.assertEqual(self.c.history_panel.reminders_table.item(0,2).text(),'示例')

    def test_example_keeps_real_camera_evidence_unchanged(self):
        with patch('study_pet.camera.VisionController.refresh_devices'):self.c.show_camera()
        policy=self.c.camera_panel.policy
        for i in range(9):
            o=Observation(i*.25,(Box(.4,.4,.6,.8),),(tuple((.5,.6) for _ in range(8)),),(Box(.2,.1,.4,.3),))
            policy.update(o,focus_active=True)
        before=policy.phone_duration
        self.assertEqual(before,2.)
        identifier=self.c.send_sample('phone');self.c.respond_to_reminder(identifier,'research')
        self.assertEqual(policy.phone_duration,before)

    def test_example_can_be_responded_to_with_bubbles_off(self):
        self.c.pet.set_bubbles_enabled(False);identifier=self.c.send_sample('care')
        panel=self.c.history_panel
        self.assertTrue(panel.isVisible());self.assertFalse(self.c.pet.bubble.isVisible())
        QTest.mouseClick(panel.response_buttons['false_positive'],Qt.MouseButton.LeftButton)
        self.assertEqual(self.c.history.reminder(identifier)['response'],'false_positive')
        self.assertEqual(self.c.history.summary()['corrections'],0)

    def test_paused_time_and_completed_round_count_are_correct(self):
        self.c.begin();self.advance(10);self.c.toggle()
        self.advance(300);self.c.toggle();self.advance(20);self.c.stop()
        row=self.c.history.sessions()[0]
        self.assertEqual((row['elapsed'],row['pause_count'],row['status']),(30.,1,'stopped'))
        self.c.begin();self.advance(60);self.c.on_tick();self.c.on_tick()
        self.assertEqual(self.c.store.today()['seconds'],90);self.assertEqual(self.c.store.today()['completed'],1)
        self.c.begin('break');self.advance(300);self.c.on_tick()
        self.assertEqual(self.c.store.today()['seconds'],90);self.assertEqual(self.c.store.today()['completed'],1)

    def test_old_round_can_be_corrected_without_muting_new_round(self):
        self.c.begin();identifier=self.event();self.advance(5);self.c.stop();self.c.begin()
        self.assertFalse(self.c.respond_to_reminder(identifier,'research'))
        self.assertTrue(self.c.respond_to_reminder(identifier,'false_positive'))
        self.assertFalse(self.c.reminder_gate.phone_paused)

    def test_response_buttons_fit_at_all_supported_scales(self):
        self.c.begin()
        for scale in (70,100,160):
            self.c.pet.dismiss_bubble();self.c.pet.set_scale(scale);anchor=self.c.pet.foot_anchor();self.event()
            bubble=self.c.pet.bubble
            self.assertFalse(bubble.label.geometry().intersects(bubble.actions.geometry()))
            self.assertFalse(bubble.close_button.geometry().intersects(bubble.label.geometry()))
            for button in bubble.action_buttons.values():
                self.assertGreaterEqual(button.height(),24)
                self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()),button.width()-4)
            self.assertAlmostEqual(anchor.x(),self.c.pet.foot_anchor().x(),delta=1)
            self.assertAlmostEqual(anchor.y(),self.c.pet.foot_anchor().y(),delta=1)


class GateTests(unittest.TestCase):
    def test_research_keeps_care_and_does_not_accumulate_muted_phone(self):
        now=[1000.];gate=ReminderGate(lambda:now[0]);gate.apply('research','phone')
        policy=ReminderPolicy(VisionSettings(phone_seconds=3,care_seconds=2))
        events=[]
        for i in range(13):
            o=Observation(1000+i*.25,(Box(.4,.4,.6,.8),),(tuple((.5,.6) for _ in range(8)),),
                (Box(.2,.1,.4,.3),),.8)
            event=policy.update(o,focus_active=True,phone_paused=gate.phone_paused)
            if event:events.append(event.kind)
        self.assertEqual(events,['care']);self.assertEqual(policy.phone_duration,0.)
        now[0]+=301;self.assertFalse(gate.phone_paused)
        gate.apply('snooze','phone');gate.reset_round();self.assertTrue(gate.snoozed)


if __name__=='__main__':unittest.main()
