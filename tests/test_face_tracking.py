from dataclasses import replace
from math import floor
import unittest

from study_pet.face_tracking import PrimaryFaceTracker
from study_pet.perception import Box,FaceFeatures,Observation,ReminderPolicy,VisionSettings,BrowCalibration

USER=Box(.25,.05,.65,.40)
SECOND_USER=Box(.72,.08,.96,.40)


def feature(box,brow):
    return FaceFeatures(box,(('browDownLeft',brow),('browDownRight',brow),('eyeLookDownLeft',.2)))


def scene(t,extra=False,phone=True,shift=0.,main=True,real=False,brow=.05,phone_timestamp=None):
    device=Box(.45+shift,.45,.70+shift,.90,.9)
    faces=([USER] if main else [])+([SECOND_USER if real else Box(.47+shift,.47,.52+shift,.53)] if extra else [])
    features=tuple(feature(box,brow if box==USER else .99) for box in faces)
    return Observation(t,(device,) if phone else (),
        (tuple((.5+shift,.65) for _ in range(8)),),tuple(faces),
        phone_timestamp=t if phone_timestamp is None else phone_timestamp,
        asynchronous=True,face_features=features,brow_valid=False)


class FaceTrackingTests(unittest.TestCase):
    def setUp(self):self.tracker=PrimaryFaceTracker()

    def warm(self,policy=None,brow=.05):
        for i in range(7):
            o=self.tracker.update(scene(round(i*.1,2),brow=brow))
            if policy is not None:policy.update(o,focus_active=True)
        return o

    def attach(self):
        self.warm()
        for t,shift in ((.8,0.),(1.1,.025),(1.4,.05)):
            o=self.tracker.update(scene(t,extra=True,shift=shift))
        return o

    def test_single_real_user_is_acquired_and_uses_current_features(self):
        o=self.warm(brow=.6)
        self.assertEqual(o.user_state,'single');self.assertEqual(o.primary_face,0)
        self.assertTrue(o.brow_reliable);self.assertAlmostEqual(o.brow_score,.6)
        self.assertEqual(o.filtered_faces,())

    def test_phone_attached_fake_is_filtered_after_distinct_captures_and_motion(self):
        o=self.attach()
        self.assertEqual(len(o.faces),2)  # Raw candidates are retained for diagnosis.
        self.assertEqual(o.filtered_faces,(1,));self.assertEqual(o.user_state,'single')
        self.assertAlmostEqual(o.brow_score,.05);self.assertTrue(o.brow_reliable)
        self.assertEqual(o.face_features[1].brow_score,.99)

    def test_false_face_does_not_prevent_phone_reminder_accumulation(self):
        p=ReminderPolicy(VisionSettings(phone_seconds=3,care_seconds=2,cooldown_seconds=30))
        self.warm(p);events=[]
        for i in range(8,55):
            t=round(i*.1,2);step=min(2,(i-8)//3);shift=step*.025
            o=self.tracker.update(scene(t,extra=True,shift=shift))
            event=p.update(o,focus_active=True)
            if event:events.append(event.kind)
        self.assertEqual(events,['phone'])

    def test_two_real_users_confirm_multiple_and_reset_evidence(self):
        p=ReminderPolicy(VisionSettings(phone_seconds=3));self.warm(p)
        before=p.phone_duration;self.assertGreater(before,0.)
        for i in range(8,23):
            o=self.tracker.update(scene(round(i*.1,2),extra=True,real=True))
            self.assertIsNone(p.update(o,focus_active=True))
        self.assertEqual(o.user_state,'multiple');self.assertEqual(o.filtered_faces,())
        self.assertEqual(p.phone_duration,0.);self.assertFalse(o.brow_reliable)

    def test_transient_extra_face_preserves_tracker_policy_evidence(self):
        p=ReminderPolicy(VisionSettings(phone_seconds=3));self.warm(p)
        for i in range(7,23):p.update(self.tracker.update(scene(round(i*.1,2))),focus_active=True)
        before=p.phone_duration
        for i in range(23,28):
            o=self.tracker.update(scene(round(i*.1,2),extra=True))
            self.assertEqual(o.user_state,'uncertain')
            self.assertIsNone(p.update(o,focus_active=True));self.assertEqual(p.phone_duration,before)
        self.assertIsNone(p.update(self.tracker.update(scene(2.8)),focus_active=True))
        self.assertEqual(p.phone_duration,before)

    def test_static_phone_overlap_alone_is_not_sufficient_to_filter_a_face(self):
        self.warm()
        for i in range(8,25):o=self.tracker.update(scene(round(i*.1,2),extra=True))
        self.assertEqual(o.filtered_faces,());self.assertEqual(o.user_state,'multiple')

    def test_missing_phone_box_does_not_keep_filtering_a_face(self):
        self.assertEqual(self.attach().filtered_faces,(1,))
        o=self.tracker.update(scene(1.5,extra=True,phone=False,shift=.05))
        self.assertEqual(o.filtered_faces,());self.assertFalse(o.has_primary)
        self.assertEqual(o.brow_score,0.);self.assertFalse(o.brow_valid)
        o=self.tracker.update(scene(1.6,extra=True,shift=.05))
        self.assertEqual(o.filtered_faces,())  # Need new attachment evidence.

    def test_missing_phone_boxes_never_hide_a_second_real_person(self):
        self.warm()
        for i in range(8,24):
            o=self.tracker.update(scene(round(i*.1,2),extra=True,real=True,phone=False))
            self.assertEqual(o.filtered_faces,())
        self.assertEqual(o.user_state,'multiple');self.assertFalse(o.brow_reliable)

    def test_old_future_out_of_order_and_nonfinite_phone_results_do_not_filter(self):
        for stamp in (.5,1.6,1.,float('nan')):
            with self.subTest(stamp=stamp):
                self.tracker=PrimaryFaceTracker();self.attach()
                o=self.tracker.update(scene(1.5,extra=True,shift=.05,phone_timestamp=stamp))
                self.assertEqual(o.filtered_faces,());self.assertFalse(o.has_primary)
        self.tracker=PrimaryFaceTracker();self.attach()
        o=self.tracker.update(replace(scene(1.5,extra=True,shift=.05),phone_fresh=False))
        self.assertEqual(o.filtered_faces,())

    def test_primary_leaves_never_promotes_phone_case_or_reuses_old_brow(self):
        self.attach()
        for i in range(15,31):
            o=self.tracker.update(scene(round(i*.1,2),extra=True,main=False,shift=.05))
            self.assertFalse(o.has_primary);self.assertFalse(o.brow_reliable)
            self.assertEqual((o.brow_score,o.eyes_down),(0.,0.))
            self.assertEqual(o.user_state,'uncertain')

    def test_known_phone_fake_cannot_become_primary_when_user_and_phone_detection_disappear(self):
        self.warm()
        def large_fake(t,shift,main=True,phone=True):
            o=scene(t,extra=True,shift=shift,main=main,phone=phone)
            fake=Box(.47+shift,.47,.57+shift,.57)  # Large enough to pass initial acquisition size.
            faces=(USER,fake) if main else (fake,)
            return replace(o,faces=faces,face_features=tuple(feature(b,.05 if b==USER else .99) for b in faces))
        for t,shift in ((.8,0.),(1.1,.025),(1.4,.05)):
            result=self.tracker.update(large_fake(t,shift))
        self.assertEqual(result.filtered_faces,(1,))
        for i in range(15,35):
            result=self.tracker.update(large_fake(round(i*.1,2),.05,main=False,phone=False))
            self.assertFalse(result.has_primary);self.assertFalse(result.brow_reliable)
            self.assertEqual(result.brow_score,0.)

    def test_degenerate_extra_box_is_not_filtered_or_allowed_to_crash_tracking(self):
        self.warm()
        for t in (.7,.8,.9):
            o=scene(t,extra=True);bad=Box(.4,.4,.4,.4)
            result=self.tracker.update(replace(o,faces=(USER,bad)))
            self.assertEqual(result.filtered_faces,());self.assertFalse(result.has_primary)

    def test_confirmed_multiple_requires_stable_single_recovery(self):
        self.warm()
        for i in range(8,23):self.tracker.update(scene(round(i*.1,2),extra=True,real=True))
        self.assertFalse(self.tracker.update(scene(2.3)).has_primary)
        self.assertTrue(self.tracker.update(scene(2.7)).has_primary)

    def test_late_phone_detection_can_recover_from_multiple_with_three_hz_skew(self):
        self.warm();results=[]
        def shift(t):return min(.1,max(0.,t-2.)*.05)
        for i in range(8,55):
            t=round(i*.1,2);stamp=max(0.,floor((t-.14)*3)/3)
            o=scene(t,extra=True,shift=shift(t),phone=t>=2.,phone_timestamp=stamp)
            if t>=2.:
                o=replace(o,phones=(Box(.45+shift(stamp),.45,.70+shift(stamp),.9,.9),))
            results.append(self.tracker.update(o))
        self.assertTrue(any(o.user_state=='multiple' for o in results))
        self.assertTrue(any(o.has_primary and o.filtered_faces for o in results if o.timestamp>3.))

    def test_weak_phone_confidence_does_not_authorize_face_filtering(self):
        self.warm()
        for t,shift in ((.8,0.),(1.1,.025),(1.4,.05)):
            o=scene(t,extra=True,shift=shift)
            result=self.tracker.update(replace(o,phones=(replace(o.phones[0],score=.4),)))
            self.assertEqual(result.filtered_faces,())

    def test_face_result_expiry_and_capture_gap_clear_primary_features(self):
        self.warm(brow=.8)
        o=self.tracker.update(replace(scene(.7,brow=.8),face_fresh=False))
        self.assertFalse(o.brow_reliable);self.assertEqual(o.brow_score,0.)
        self.assertFalse(self.tracker.update(scene(2.,brow=.8)).has_primary)

    def test_reordering_faces_does_not_swap_primary_blendshapes(self):
        o=self.attach()
        o=replace(scene(1.5,extra=True,shift=.05),faces=tuple(reversed(o.faces)),
            face_features=tuple(reversed(o.face_features)))
        result=self.tracker.update(o)
        self.assertEqual(result.primary_face,1);self.assertEqual(result.filtered_faces,(0,))
        self.assertAlmostEqual(result.brow_score,.05)

    def test_missing_primary_vector_never_borrows_fake_face_vector(self):
        o=self.attach()
        o=replace(scene(1.5,extra=True,shift=.05),faces=tuple(reversed(o.faces)),
            face_features=(o.face_features[1],))
        result=self.tracker.update(o)
        self.assertTrue(result.has_primary);self.assertEqual(result.primary_face,1)
        self.assertFalse(result.brow_reliable);self.assertEqual(result.brow_score,0.)

    def test_returning_primary_uses_new_features_instead_of_pre_leave_scores(self):
        self.warm(brow=.8)
        absent=self.tracker.update(scene(.7,main=False))
        self.assertFalse(absent.brow_reliable);self.assertEqual(absent.brow_score,0.)
        returned=self.tracker.update(scene(.8,brow=.1))
        self.assertTrue(returned.brow_reliable);self.assertEqual(returned.brow_score,.1)

    def test_missing_primary_blendshapes_cannot_trigger_care_or_calibrate(self):
        self.warm()
        for i in range(7,15):
            o=self.tracker.update(replace(scene(round(i*.1,2)),face_features=()))
            self.assertTrue(o.has_primary);self.assertFalse(o.brow_reliable)
            self.assertIsNone(BrowCalibration().add(o))

    def test_previously_independent_face_cannot_be_filtered_by_later_overlap(self):
        self.warm()
        # A second small face, first observed independently of the phone.
        outside=Box(.71,.47,.76,.53)
        for i in range(8,14):
            o=scene(round(i*.1,2),extra=True)
            self.tracker.update(replace(o,faces=(USER,outside),face_features=(feature(USER,.05),feature(outside,.99))))
        # Move the phone to that face, then move both together.
        for i in range(14,25):
            shift=(i-14)*.005
            o=scene(round(i*.1,2),extra=True,shift=.24+shift)
            result=self.tracker.update(o)
            self.assertEqual(result.filtered_faces,())


class UncertainEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.p=ReminderPolicy(VisionSettings(phone_seconds=3,care_seconds=2))
        for i in range(9):self.p.update(scene(i*.25),focus_active=True)
        self.assertEqual(self.p.phone_duration,2.)

    def test_brief_extra_face_keeps_evidence_but_counts_no_uncertain_time(self):
        for t in (2.25,2.5,2.75):
            o=replace(scene(t,extra=True),face_state='uncertain')
            self.assertIsNone(self.p.update(o,focus_active=True))
            self.assertEqual(self.p.phone_duration,2.)
        self.assertIsNone(self.p.update(scene(3.),focus_active=True))
        self.assertEqual(self.p.phone_duration,2.)
        for t in (3.25,3.5,3.75):self.assertIsNone(self.p.update(scene(t),focus_active=True))
        self.assertEqual(self.p.update(scene(4.),focus_active=True).kind,'phone')

    def test_uncertainty_retention_is_bounded(self):
        for i in range(9,17):
            self.assertIsNone(self.p.update(replace(scene(i*.25),face_state='uncertain'),focus_active=True))
        self.assertEqual(self.p.phone_duration,0.)
        self.assertIsNone(self.p.update(scene(4.25),focus_active=True))
        self.assertEqual(self.p.phone_duration,0.)

    def test_confirmed_multiple_pauses_and_resets_immediately(self):
        self.assertIsNone(self.p.update(replace(scene(2.25,extra=True),face_state='multiple'),focus_active=True))
        self.assertEqual(self.p.phone_duration,0.)

    def test_primary_change_cannot_inherit_another_users_evidence(self):
        o=replace(scene(2.25),primary_face=0,primary_id=2,face_state='single')
        self.assertIsNone(self.p.update(o,focus_active=True));self.assertEqual(self.p.phone_duration,0.)

    def test_pauses_during_uncertainty_still_clear_the_relevant_evidence(self):
        self.p.update(replace(scene(2.25),face_state='uncertain'),focus_active=True,phone_paused=True)
        self.assertEqual(self.p.phone_duration,0.)


if __name__=='__main__':unittest.main()
