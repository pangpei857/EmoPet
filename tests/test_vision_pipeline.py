import threading
import time
import unittest

from study_pet.perception import Observation
from study_pet.vision_pipeline import LatestFrames,ParallelAnalysis


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


if __name__=='__main__':unittest.main()
