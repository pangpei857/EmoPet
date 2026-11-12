import unittest
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject,Signal,Qt,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from study_pet.camera_ui import CameraPanel
from study_pet.perception import Box,FaceFeatures,Observation,VisionSettings
from study_pet.face_tracking import PrimaryFaceTracker
from study_pet.ui import Companion,STYLE
from study_pet.storage import Store

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet(STYLE)


class FakeController(QObject):
    state_changed=Signal(str,str);devices_changed=Signal(object);frame_ready=Signal(object)
    observation_ready=Signal(object)
    def __init__(self):
        super().__init__();self.state='off';self.starts=[];self.stops=0;self.scans=0
    @property
    def active(self):return self.state in {'starting','running','stopping'}
    def refresh_devices(self):self.scans+=1
    def start(self,*args):
        self.starts.append(args);self.state='running';self.state_changed.emit('running','已开启');return True
    def stop(self):self.stops+=1;self.state='off';self.state_changed.emit('off','已关闭')


class CameraUiTests(unittest.TestCase):
    def setUp(self):
        self.controller=FakeController();self.focus=True;self.visible=True
        self.panel=CameraPanel(self.controller,VisionSettings(phone_seconds=3),context=lambda:(self.focus,self.visible))
        self.events=[];self.saved=[]
        self.panel.feedback_requested.connect(self.events.append);self.panel.settings_changed.connect(self.saved.append)
        self.panel.show();APP.processEvents()

    def tearDown(self):
        self.panel.close();self.panel.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()

    def frames(self,brow=0.,phone=True):
        for i in range(17):
            points=tuple((.48,.6) for _ in range(8))
            o=Observation(i*.25,(Box(.4,.4,.6,.8,.9),) if phone else (),(points,),
                (Box(.2,.1,.5,.3),),brow)
            self.controller.observation_ready.emit(o)
            self.controller.frame_ready.emit({'width':16,'height':12,'rgb':bytes(16*12*3)})

    def test_default_is_off_and_device_selection_starts_explicitly(self):
        self.assertEqual(self.controller.starts,[])
        self.panel.on_devices([{'name':'测试摄像头','index':2,'backend':700}])
        QTest.mouseClick(self.panel.start,Qt.MouseButton.LeftButton)
        self.assertEqual(self.controller.starts,[(2,700)])
        self.panel.close();self.assertEqual(self.controller.stops,1)
        self.assertIsNone(self.panel.preview.image)

    def test_running_observations_link_to_feedback_once(self):
        self.controller.start(0,700);self.frames()
        self.assertEqual([event.kind for event in self.events],['phone'])
        self.assertIsNotNone(self.panel.preview.image)
        self.assertIn('刚刚提醒',self.panel.notice.text())

    def test_video_test_and_hidden_pet_do_not_trigger(self):
        self.controller.start('video.avi');self.panel._video_mode=True;self.frames()
        self.assertEqual(self.events,[])
        self.panel._video_mode=False;self.visible=False;self.frames()
        self.assertEqual(self.events,[])

    def test_pause_settings_and_error_clear_pending_evidence(self):
        self.controller.start(0,700)
        QTest.mouseClick(self.panel.snooze,Qt.MouseButton.LeftButton);self.frames()
        self.assertEqual(self.events,[])
        self.panel.phone.setChecked(False)
        self.assertFalse(self.saved[-1]['phone_enabled'])
        self.controller.state='error';self.controller.state_changed.emit('error','设备已断开')
        self.assertIsNone(self.panel.preview.image)
        self.assertEqual(self.panel.policy.phone_duration,0.)
        self.assertIn('设备已断开',self.panel.status.text())

    def test_calibration_stores_only_numeric_baseline(self):
        self.controller.start(0,700);self.panel.begin_calibration();self.frames(brow=.2,phone=False)
        self.assertIsNone(self.panel.calibration)
        self.assertAlmostEqual(self.saved[-1]['baseline'],.2)
        self.assertEqual(self.events,[])
        self.assertAlmostEqual(self.panel.brow.value(),.45)
        self.assertIn('0.45',self.panel.baseline_label.text())
        QTest.mouseClick(self.panel.apply_recommended,Qt.MouseButton.LeftButton)
        self.assertAlmostEqual(self.panel.brow.value(),.38)

    def test_fast_preview_does_not_accumulate_duplicate_detection_evidence(self):
        self.controller.start(0,700)
        self.frames(phone=False)
        for _ in range(120):
            self.controller.frame_ready.emit({'width':16,'height':12,'rgb':bytes(16*12*3)})
        self.assertEqual(self.events,[])
        self.assertEqual(self.panel.policy.phone_duration,0.)

    def test_manual_point_one_threshold_survives_calibration_and_restore(self):
        self.controller.start(0,700);self.panel.brow.setValue(.10)
        self.panel.begin_calibration();self.frames(brow=.2,phone=False)
        settings=VisionSettings.from_dict(self.saved[-1])
        self.assertEqual(settings.brow_threshold,.10)
        self.assertEqual(self.panel.settings.brow_threshold,.10)
        self.assertIn('实际生效阈值：0.10',self.panel.baseline_label.text())

    def test_diagnostics_distinguish_detection_from_hand_relation(self):
        self.controller.start(0,700)
        self.controller.observation_ready.emit(Observation(0.,(Box(.4,.4,.6,.8,.9),),faces=(Box(.2,.1,.4,.3),)))
        self.assertIn('已识别手机，未检测到手部',self.panel.diagnostics.text())
        self.assertIn('90%',self.panel.details.text())
        self.panel.focus_only.setChecked(True);self.focus=False;self.panel.update_diagnostics(force=True)
        self.assertIn('尚未开始专注计时',self.panel.diagnostics.text())

    def test_resolved_fake_face_does_not_display_multiple_people_or_block_calibration(self):
        self.controller.start(0,700);tracker=PrimaryFaceTracker()
        main=Box(.2,.05,.6,.4)
        for i in range(50):
            t=round(i*.1,2);shift=min(.05,max(0.,(i-8)*.005))
            phone=Box(.45+shift,.45,.70+shift,.9,.9)
            fake=Box(.47+shift,.47,.52+shift,.53)
            faces=(main,fake) if i>=8 else (main,)
            features=tuple(FaceFeatures(box,(('browDownLeft',.1 if j==0 else .99),
                ('browDownRight',.1 if j==0 else .99))) for j,box in enumerate(faces))
            o=tracker.update(Observation(t,(phone,),faces=faces,phone_timestamp=t,face_features=features))
            if i==18:self.panel.begin_calibration()
            self.controller.observation_ready.emit(o)
        self.panel.update_diagnostics(force=True)
        self.assertEqual(o.filtered_faces,(1,));self.assertIn('已排除疑似手机假脸',self.panel.details.text())
        self.assertNotIn('多人',self.panel.diagnostics.text())
        self.assertIsNone(self.panel.calibration);self.assertAlmostEqual(self.panel.settings.baseline,.1)

    def test_face_diagnostics_are_logged_by_parent_without_recording_features(self):
        self.controller.start(0,700)
        o=Observation(time.monotonic(),faces=(Box(.2,.1,.5,.4),Box(.43,.43,.47,.47)),
            face_state='uncertain',face_reason='phone_candidate_pending',primary_face=0,primary_id=1)
        with self.assertLogs('study_pet.face_tracking',level='INFO') as captured:
            self.controller.observation_ready.emit(o)
        self.assertIn('reason=phone_candidate_pending',captured.output[0])
        self.assertIn('candidates=2',captured.output[0])
        self.assertNotIn('blendshape',captured.output[0])

    def test_small_panel_keeps_values_readable_and_plus_minus_work(self):
        self.panel.resize(860,620);APP.processEvents()
        for control,step in ((self.panel.phone_duration,1),(self.panel.care_duration,1),
                             (self.panel.cooldown,1),(self.panel.brow,.01)):
            self.panel.settings_scroll.ensureWidgetVisible(control);APP.processEvents()
            editor=control.lineEdit()
            self.assertGreaterEqual(editor.height(),editor.fontMetrics().height()+4)
            self.assertGreaterEqual(editor.width(),editor.fontMetrics().horizontalAdvance(control.text())+8)
            self.assertEqual(control.plus_button.text(),'+');self.assertEqual(control.minus_button.text(),'−')
            original=control.value()
            QTest.mouseClick(control.plus_button,Qt.MouseButton.LeftButton)
            self.assertAlmostEqual(control.value(),original+step)
            QTest.mouseClick(control.minus_button,Qt.MouseButton.LeftButton)
            self.assertAlmostEqual(control.value(),original)
            control.setValue(control.maximum());self.assertFalse(control.plus_button.isEnabled())
            control.setValue(control.minimum());self.assertFalse(control.minus_button.isEnabled())
        self.assertTrue(self.panel.settings_scroll.verticalScrollBar().isVisible())


class CompanionVisionTests(unittest.TestCase):
    def test_stable_observations_reach_pet_and_hidden_pet_stays_hidden(self):
        temporary=tempfile.TemporaryDirectory(prefix='pet-camera-link-')
        companion=Companion(Store(Path(temporary.name)),tray_enabled=False)
        try:
            with patch('study_pet.camera.VisionController.refresh_devices'):
                companion.show_camera()
            panel=companion.camera_panel;controller=companion.vision_controller
            self.assertEqual(controller.state,'off')
            self.assertIsNone(controller.process)
            companion.session.start(1,'测试任务')
            panel.phone_duration.setValue(3);controller.set_state('running','测试观察')
            def feed(start):
                for i in range(17):
                    o=Observation(start+i*.25,(Box(.4,.4,.6,.8,.9),),
                        (tuple((.48,.6) for _ in range(8)),),(Box(.2,.1,.5,.3),))
                    panel.on_observation(o)
                    panel.on_frame({'width':16,'height':12,'rgb':bytes(16*12*3)})
            feed(0.)
            self.assertEqual(companion.pet.canvas.mood,'remind')
            self.assertIn('手机',companion.pet.bubble.raw_text)
            self.assertEqual(companion.store.get('vision')['phone_seconds'],3)
            companion.pet.hide();feed(200.)
            self.assertFalse(companion.pet.isVisible())
            self.assertEqual(panel.policy.phone_duration,0.)
        finally:
            companion.shutdown_vision();companion.camera_panel.close()
            companion.timer.stop();companion.pet.hide();companion.panel.hide()
            companion.camera_panel.deleteLater();companion.pet.deleteLater();companion.panel.deleteLater()
            APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents();temporary.cleanup()


if __name__=='__main__':unittest.main()
