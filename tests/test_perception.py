import unittest
from dataclasses import replace
from study_pet.perception import Box, Observation, VisionSettings, ReminderPolicy, BrowCalibration

PHONE=Box(.4,.4,.6,.8,.9)
FACE=Box(.3,.05,.7,.35)
HAND=tuple((.43+i*.01,.6) for i in range(8))

def observation(t,phone=True,hand=True,faces=1,brow=0.):
    return Observation(t,(PHONE,) if phone else (),(HAND,) if hand else (),tuple(FACE for _ in range(faces)),brow)


class ReminderTests(unittest.TestCase):
    def setUp(self):self.p=ReminderPolicy(VisionSettings(phone_seconds=3,care_seconds=2,cooldown_seconds=30))

    def feed(self,start,end,**kwargs):
        result=[]
        for step in range(round(start*4),round(end*4)+1):
            event=self.p.update(observation(step/4,**kwargs),focus_active=True)
            if event:result.append(event)
        return result

    def test_phone_on_desk_and_face_absence_do_not_trigger(self):
        self.assertEqual(self.feed(0,6,hand=False),[])
        self.assertEqual(self.feed(7,14,faces=0),[])
        self.assertEqual(self.feed(15,20,phone=False),[])

    def test_phone_needs_sustained_hand_relation_then_cooldown(self):
        self.assertEqual(self.feed(0,2),[])
        events=self.feed(2.25,12)
        self.assertEqual([e.kind for e in events],['phone'])
        self.assertEqual(self.feed(12.25,31),[])
        self.assertEqual([e.kind for e in self.feed(31.25,34)],['phone'])

    def test_brief_dropout_is_not_added_to_evidence(self):
        self.feed(0,2)
        self.p.update(observation(2.25,hand=False),focus_active=True)
        self.assertIsNone(self.p.update(observation(2.5),focus_active=True))
        self.assertAlmostEqual(self.p.phone_duration,2.)
        self.assertEqual([e.kind for e in self.feed(2.75,3.5)],['phone'])

    def test_long_gap_or_lost_detection_starts_over(self):
        self.feed(0,2)
        self.assertIsNone(self.p.update(observation(20),focus_active=True))
        self.assertEqual(self.p.phone_duration,0.)
        self.feed(20.25,22)
        self.feed(22.25,24,hand=False)
        self.assertIsNone(self.p.update(observation(24.25),focus_active=True))
        self.assertEqual(self.p.phone_duration,0.)

    def test_focus_pause_hidden_and_snooze_reset_accumulation(self):
        for extra in ({'focus_active':False},{'focus_active':True,'pet_visible':False},{'focus_active':True,'snoozed':True}):
            self.p=ReminderPolicy(VisionSettings(phone_seconds=3))
            self.feed(0,2)
            self.assertIsNone(self.p.update(observation(2.25),**extra))
            self.assertEqual(self.p.phone_duration,0.)

    def test_multiple_faces_reset_immediately(self):
        self.feed(0,2.75)
        self.assertIsNone(self.p.update(observation(3,faces=2),focus_active=True))
        self.assertEqual(self.p.phone_duration,0.)
        self.assertEqual(self.feed(3.25,5.75),[])

    def test_brow_uses_manual_threshold_despite_baseline_and_shares_cooldown(self):
        self.p.settings.baseline=.5
        self.p.settings.brow_threshold=.10
        self.assertEqual(self.feed(0,1.75,phone=False,brow=.12),[])
        self.assertEqual([e.kind for e in self.feed(2,4,phone=False,brow=.12)],['care'])
        self.assertEqual(self.feed(7.25,15),[])

    def test_point_one_threshold_is_saved_and_restored(self):
        self.assertEqual(VisionSettings.from_dict({'brow_threshold':.10}).brow_threshold,.10)
        self.assertEqual(VisionSettings.from_dict({'brow_threshold':-.5}).brow_threshold,.10)

    def test_expired_async_phone_and_face_cannot_trigger_reminders(self):
        o=replace(observation(10),asynchronous=True,phone_timestamp=10.)
        self.assertTrue(o.freshened(10.2).phone_near_hand)
        expired=o.freshened(11.)
        self.assertFalse(expired.phone_near_hand)
        self.assertFalse(expired.face_fresh)
        self.assertIsNone(self.p.update(expired,focus_active=True))
        fresh_face=replace(o,timestamp=11.).freshened(11.1)
        self.assertTrue(fresh_face.face_fresh);self.assertFalse(fresh_face.phone_fresh)
        self.assertFalse(fresh_face.phone_near_hand)

    def test_async_capture_gaps_do_not_count_stale_time(self):
        for t in (10.,10.25,10.5):
            self.p.update(replace(observation(t),asynchronous=True,phone_timestamp=t),focus_active=True)
        self.assertEqual(self.p.phone_duration,.5)
        self.p.update(replace(observation(11.5),asynchronous=True,phone_timestamp=11.5),focus_active=True)
        self.assertEqual(self.p.phone_duration,0.)

    def test_feature_switches_and_focus_only(self):
        self.p.settings.phone_enabled=False;self.p.settings.care_enabled=False
        self.assertEqual(self.feed(0,8,brow=.9),[])
        self.p.settings.phone_enabled=True;self.p.settings.focus_only=False
        events=[self.p.update(observation(9+i*.25),focus_active=False) for i in range(16)]
        self.assertEqual(len([e for e in events if e]),1)

    def test_natural_baseline_uses_single_face_and_restarts_on_loss(self):
        calibration=BrowCalibration()
        for i in range(10):self.assertIsNone(calibration.add(observation(i*.2,brow=.1)))
        calibration.add(observation(2.,faces=0))
        for i in range(12):self.assertIsNone(calibration.add(observation(3+i*.25,brow=.2)))
        self.assertAlmostEqual(calibration.add(observation(6.,brow=.2)),.2)

    def test_saved_settings_are_bounded_and_nonfinite_ignored(self):
        s=VisionSettings.from_dict({'phone_seconds':-99,'cooldown_seconds':9999,'care_seconds':'bad',
            'brow_threshold':float('nan'),'baseline':float('inf'),'phone_enabled':'yes'})
        self.assertEqual((s.phone_seconds,s.cooldown_seconds,s.care_seconds),(3,600,5))
        self.assertEqual(s.brow_threshold,.45);self.assertIsNone(s.baseline);self.assertTrue(s.phone_enabled)


if __name__=='__main__':unittest.main()
