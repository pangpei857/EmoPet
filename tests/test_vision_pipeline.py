import threading
import time
import unittest
from unittest.mock import Mock, patch
from math import floor

from study_pet.perception import Box,FaceFeatures,Observation
from study_pet.vision_pipeline import CapturedFrame,LatestFrames,ParallelAnalysis


class PipelineTests(unittest.TestCase):
    def test_capture_overwrites_busy_consumers_backlog(self):
        frames=LatestFrames();stop=threading.Event()
        for number in range(100):frames.publish(number,float(number))
        frame=frames.next(0,stop)
        self.assertEqual((frame.sequence,frame.image,frame.timestamp),(100,99,99.))
        stop.set();self.assertIsNone(frames.next(0,stop))

    def test_slow_phone_does_not_block_face_or_replay_old_capture_frames(self):
        entered=threading.Event();release=threading.Event();stop=threading.Event()
        frames=LatestFrames();observations=[];feature_inputs=[]
        class Features:
            def analyze_features(self,image,timestamp):
                feature_inputs.append(image)
                return None,Observation(timestamp)
        class Phone:
            def detect(self,image):
                entered.set();release.wait(2.)
                return ()
        pipeline=ParallelAnalysis(frames,Features(),Phone(),stop,observations.append)
        try:
            pipeline.start();frames.publish(0,time.monotonic())
            self.assertTrue(entered.wait(1.))
            deadline=time.monotonic()+.5;number=0
            while time.monotonic()<deadline:
                number+=1;frames.publish(number,time.monotonic());time.sleep(.01)
            self.assertGreaterEqual(len(observations),4)
            self.assertFalse(release.is_set())
            self.assertGreater(feature_inputs[-1],number//2)
            self.assertTrue(all(item['type']=='observation' for item in observations))
            self.assertTrue(all(not item['observation'].phone_fresh for item in observations))
        finally:
            release.set();self.assertTrue(pipeline.close())

    def test_detector_failure_stops_the_pipeline_and_reports_error(self):
        stop=threading.Event();frames=LatestFrames();messages=[]
        class Features:
            def analyze_features(self,image,timestamp):raise RuntimeError('test detector failure')
        class Phone:
            def detect(self,image):return ()
        pipeline=ParallelAnalysis(frames,Features(),Phone(),stop,messages.append)
        try:
            with self.assertLogs(level='ERROR'):
                pipeline.start();frames.publish(None,time.monotonic())
                self.assertTrue(stop.wait(1.))
            self.assertEqual([item['type'] for item in messages],['error'])
        finally:self.assertTrue(pipeline.close())

    def test_body_receives_the_same_single_person_frame_and_expires_with_it(self):
        person = Box(.2,.15,.8,.88,.94)
        pose = tuple((.5,.5,.9) for _ in range(17))
        image = object()
        original = object()
        estimator = Mock()
        estimator.estimate.return_value = pose
        for people in ((person,), (person, person)):
            with self.subTest(people=len(people)):
                detector = Mock()
                detector.detect_objects.return_value = (), people
                stop = Mock()
                stop.is_set.side_effect = (False, False, True) if len(people)==1 else (False, True)
                frames = Mock()
                frames.next.return_value = CapturedFrame(1,10.,image,original if len(people)==1 else None)
                estimator.reset_mock()
                pipeline = ParallelAnalysis(frames,None,detector,stop,Mock(),body=estimator)
                pipeline.phone_loop()
                if len(people) == 1:
                    detector.detect_objects.assert_called_once_with(image,original_image=original)
                    estimator.estimate.assert_called_once_with(image,person)
                    self.assertEqual(pipeline.phone_result[5],pose)
                else:
                    detector.detect_objects.assert_called_once_with(image)
                    estimator.estimate.assert_not_called()
                    self.assertEqual(pipeline.phone_result[5],())
        observation = Observation(10.1,phone_timestamp=10.,asynchronous=True,
                                  person_fresh=True,persons=(person,),body_points=pose)
        self.assertEqual(observation.freshened(10.2).body_points,pose)
        self.assertEqual(observation.freshened(11.).body_points,())

    def test_face_resolution_receives_merged_three_hz_phone_results(self):
        stop=threading.Event();output=[]
        class Clock:
            value=0.
            def monotonic(self):return self.value
        clock=Clock()
        def device(t):
            shift=min(.05,max(0.,t-.8)*.05)
            return Box(.45+shift,.45,.70+shift,.9,.9)
        class Frames:
            sequence=0
            def next(self,after,event):
                if self.sequence>=41:event.set();return None
                t=round(self.sequence*.1,2);self.sequence+=1;clock.value=t+.02
                stamp=max(0.,floor((t-.14)*3)/3)
                pipeline.phone_result=(stamp,(device(stamp),),140.,3.)
                main=Box(.25,.05,.65,.4);p=device(t)
                faces=(main,Box(p.x1+.02,.47,p.x1+.07,.53)) if t>=.8 else (main,)
                features=tuple(FaceFeatures(b,(('browDownLeft',.1 if j==0 else .99),
                    ('browDownRight',.1 if j==0 else .99))) for j,b in enumerate(faces))
                return CapturedFrame(self.sequence,t,Observation(t,faces=faces,face_features=features))
        class Features:
            def analyze_features(self,image,timestamp):return None,image
        class Stop:
            def is_set(self):return stop.is_set()
            def set(self):stop.set()
            def wait(self,delay):pass
        pipeline=ParallelAnalysis(Frames(),Features(),None,Stop(),output.append)
        with patch('study_pet.vision_pipeline.time',clock):pipeline.face_loop()
        resolved=[item['observation'] for item in output if item['observation'].filtered_faces]
        self.assertTrue(resolved)
        self.assertTrue(all(o.has_primary and o.primary_face==0 and o.brow_score==.1 for o in resolved))
        self.assertTrue(all(o.phone_timestamp is not None and o.phone_fresh for o in resolved))


if __name__=='__main__':unittest.main()
