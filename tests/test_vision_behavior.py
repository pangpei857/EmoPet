import unittest
from dataclasses import replace

from study_pet.perception import Box, FaceFeatures, Observation, VisionSettings, ReminderPolicy, BrowCalibration, ReminderGate
from study_pet.vision_behavior import BehaviorTracker, BrowSignal, head_down


FACE=Box(.3,.12,.6,.5)
PERSON=Box(.15,.06,.8,.98,.95)
PHONE=Box(.4,.5,.6,.85,.9)
HAND=tuple((.48,.6) for _ in range(8))


def observed(t,score=.1,yaw=43.,pitch=8.,quality=True,phone=False):
    feature=FaceFeatures(FACE,(('browDownLeft',score),('browDownRight',score)),
        yaw=yaw,pitch=pitch,quality_ok=quality,brow_geometry=.3)
    return Observation(t,phones=(PHONE,) if phone else (),hands=(HAND,) if phone else (),
        faces=(FACE,),brow_score=score,face_features=(feature,),primary_face=0,primary_id=1,
        face_state='single',persons=(PERSON,),person_fresh=True)


class PersonalViewTests(unittest.TestCase):
    def test_side_camera_is_calibrated_as_normal_and_relative_pitch_detects_lowering(self):
        settings=VisionSettings(neutral_yaw=43.,neutral_pitch=8.)
        signal=BrowSignal(settings)
        normal=signal.apply(observed(0.))
        self.assertTrue(normal.brow_reliable)
        self.assertFalse(head_down(normal,settings))
        lowered=signal.apply(observed(.2,pitch=31.))
        self.assertTrue(head_down(lowered,settings))

    def test_visible_brow_does_not_average_hidden_far_brow_to_zero(self):
        feature=FaceFeatures(FACE,(('browDownLeft',.8),('browDownRight',.0)),
            yaw=50.,pitch=0.,left_visibility=.06,right_visibility=.015)
        self.assertAlmostEqual(feature.brow_score,.8)

    def test_extreme_turn_quality_loss_and_changed_view_do_not_emit_brow_positives(self):
        signal=BrowSignal(VisionSettings(neutral_yaw=40.))
        for index,kwargs in enumerate(({'yaw':82.},{'quality':False},{'yaw':0.})):
            result=signal.apply(observed(index*.2,score=.95,**kwargs))
            self.assertFalse(result.brow_valid)
            self.assertFalse(result.brow_active)

    def test_smoothing_hysteresis_and_loss_do_not_bridge_users(self):
        signal=BrowSignal(VisionSettings(brow_threshold=.45))
        self.assertFalse(signal.apply(observed(0.,score=.1)).brow_active)
        self.assertFalse(signal.apply(observed(.05,score=.9)).brow_active)
        for i in range(1,20):result=signal.apply(observed(.05+i*.1,score=.8))
        self.assertTrue(result.brow_active)
        signal.apply(Observation(2.1))
        result=signal.apply(observed(2.2,score=.1))
        self.assertFalse(result.brow_active)

    def test_calibration_uses_personal_positive_separation_and_rejects_mixed_users(self):
        settings=VisionSettings(baseline=.1,frown_baseline=.7,baseline_noise=.02)
        self.assertEqual(settings.recommended_brow_threshold,.4)
        calibration=BrowCalibration()
        for i in range(10):calibration.add(observed(i*.2,score=.1))
        for i in range(10):
            result=calibration.add(replace(observed(2+i*.2,score=.8),primary_id=2))
        self.assertIsNone(result)
        self.assertTrue(all(v==.8 for v in calibration.samples))

    def test_feedback_pauses_are_independent(self):
        gate=ReminderGate(clock=lambda:100.)
        gate.apply('paper','head_down')
        self.assertTrue(gate.head_paused);self.assertFalse(gate.care_paused)
        gate.apply('thinking','care');self.assertTrue(gate.care_paused)
        gate.reset_round();self.assertFalse(gate.head_paused);self.assertFalse(gate.care_paused)


class BehaviorIntervalTests(unittest.TestCase):
    def setUp(self):
        self.settings=VisionSettings(phone_seconds=3,care_seconds=2,presence_seconds=5)
        self.tracker=BehaviorTracker(self.settings)

    def test_long_phone_action_is_one_id_even_when_reminder_is_muted(self):
        events=[]
        for i in range(81):events+=self.tracker.update(observed(i*.25,phone=True))
        events+=self.tracker.flush()
        phone=[e for e in events if e['type']=='phone']
        self.assertEqual(len({e['id'] for e in phone}),1)
        self.assertEqual(phone[-1]['status'],'closed')
        self.assertEqual(phone[-1]['duration'],20.)
        self.assertIn('+00:00',phone[-1]['started_at'])

    def test_missing_face_alone_is_unknown_not_away(self):
        self.tracker.update(observed(0.))
        for i in range(1,81):self.tracker.update(Observation(i*.25))
        self.assertEqual(self.tracker.state,'unknown')

    def test_associated_torso_keeps_presence_when_side_face_disappears(self):
        self.tracker.update(observed(0.))
        o=Observation(.25,persons=(PERSON,),person_fresh=True,face_state='uncertain')
        self.tracker.update(o)
        self.assertEqual(self.tracker.state,'present')

    def test_body_anchor_expires_and_cannot_be_reused_after_capture_gap(self):
        self.tracker.update(observed(0.))
        for i in range(1,30):
            self.tracker.update(Observation(i*.25,persons=(PERSON,),person_fresh=True,face_state='uncertain'))
        self.assertEqual(self.tracker.state,'unknown')
        self.tracker.update(observed(8.))
        self.tracker.update(Observation(20.,persons=(PERSON,),person_fresh=True,face_state='uncertain'))
        self.assertEqual(self.tracker.state,'unknown')

    def test_body_after_confirmed_absence_requires_reliable_face_reacquisition(self):
        self.tracker.update(observed(0.))
        for i in range(1,26):self.tracker.update(Observation(i*.25,person_fresh=True,face_state='uncertain'))
        self.assertEqual(self.tracker.state,'away')
        self.tracker.update(Observation(6.5,persons=(PERSON,),person_fresh=True,face_state='uncertain'))
        self.assertEqual(self.tracker.state,'unknown')
        self.tracker.update(observed(6.75))
        self.assertEqual(self.tracker.state,'present')

    def test_absence_requires_prior_person_anchor_and_fresh_repeated_negative(self):
        self.tracker.update(observed(0.))
        for i in range(1,26):
            self.tracker.update(Observation(i*.25,person_fresh=True,face_state='uncertain'))
        self.assertEqual(self.tracker.state,'away')
        self.tracker.update(Observation(6.5,person_fresh=True,frame_ok=False))
        self.assertEqual(self.tracker.state,'unknown')

    def test_capture_gap_closes_intervals_and_does_not_count_gap(self):
        events=[]
        for start in (0.,12.):
            for i in range(17):events+=self.tracker.update(observed(start+i*.25,phone=True))
        events+=self.tracker.flush()
        closed=[e for e in events if e['type']=='phone' and e['status']=='closed']
        self.assertEqual(len(closed),2)
        self.assertEqual(sum(e['duration'] for e in closed),8.)

    def test_unchanged_sample_time_is_not_counted_again(self):
        self.tracker.update(observed(0.,phone=True))
        self.tracker.update(observed(.5,phone=True))
        for _ in range(50):self.tracker.update(observed(.5,phone=True))
        self.assertAlmostEqual(self.tracker.segments['phone']['duration'],.5)

    def test_brief_unknown_keeps_id_but_does_not_count_unknown_or_first_recovery_interval(self):
        for i in range(17):self.tracker.update(observed(i*.25,phone=True))
        identifier=self.tracker.event_id('phone')
        self.tracker.update(replace(observed(4.25,phone=True),phone_fresh=False))
        self.tracker.update(observed(4.5,phone=True))
        self.assertEqual(self.tracker.event_id('phone'),identifier)
        self.assertEqual(self.tracker.segments['phone']['duration'],4.)
        self.tracker.update(observed(4.75,phone=True))
        self.assertEqual(self.tracker.segments['phone']['duration'],4.25)

    def test_long_unknown_closes_phone_without_counting_occlusion(self):
        for i in range(17):self.tracker.update(observed(i*.25,phone=True))
        events=[]
        for i in range(1,8):events+=self.tracker.update(replace(observed(4+i*.25),phone_fresh=False))
        closed=[e for e in events if e['type']=='phone' and e['status']=='closed']
        self.assertEqual(len(closed),1)
        self.assertEqual(closed[0]['duration'],4.)

    def test_short_action_is_not_committed_and_unknown_ends_valid_action(self):
        events=[]
        for i in range(5):events+=self.tracker.update(observed(i*.25,phone=True))
        events+=self.tracker.update(Observation(1.25))
        self.assertFalse(any(e['type']=='phone' for e in events))

    def test_pause_flushes_and_new_round_can_reset(self):
        for i in range(17):self.tracker.update(observed(i*.25,phone=True))
        events=self.tracker.update(observed(4.25),active=False)
        self.assertTrue(any(e['type']=='phone' and e['status']=='closed' for e in events))
        self.tracker.reset()
        self.assertEqual(self.tracker.segments,{})


if __name__=='__main__':unittest.main()
