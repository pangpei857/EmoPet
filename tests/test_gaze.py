import math
import unittest
from study_pet.gaze import EYE_MID_X, EYE_MID_Y, gaze_direction, smooth_gaze


class GazeTests(unittest.TestCase):
    def test_below_face_and_outside_window_keep_changing(self):
        levels=[gaze_direction(EYE_MID_X,y)[1] for y in (EYE_MID_Y+1,175,230,300,600,1200)]
        self.assertTrue(all(a<b for a,b in zip(levels,levels[1:])))
        self.assertGreater(levels[-1]-levels[2],.3)

    def test_all_directions_and_extreme_positions_remain_bounded(self):
        for x,y in ((0,125),(280,125),(140,-200),(140,600),(-5000,5000),(5000,-5000)):
            horizontal,vertical=gaze_direction(x,y)
            self.assertEqual(math.copysign(1,horizontal),math.copysign(1,x-EYE_MID_X))
            if y!=EYE_MID_Y:self.assertEqual(math.copysign(1,vertical),math.copysign(1,y-EYE_MID_Y))
            self.assertLess(math.hypot(horizontal,vertical),1.)
        self.assertEqual(gaze_direction(EYE_MID_X,EYE_MID_Y),(0.,0.))

    def test_smoothing_is_frame_rate_independent(self):
        target=(.6,.7);one_step=smooth_gaze((0.,0.),target,.2)
        two_steps=smooth_gaze(smooth_gaze((0.,0.),target,.1),target,.1)
        for a,b in zip(one_step,two_steps):self.assertAlmostEqual(a,b)
        self.assertTrue(0<one_step[1]<target[1])


if __name__=="__main__":unittest.main()
