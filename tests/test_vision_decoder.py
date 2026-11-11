import unittest
import numpy as np
from study_pet.vision import decode_phones


class PhoneDecoderTests(unittest.TestCase):
    def test_letterbox_coordinates_nms_and_class_disambiguation(self):
        output=np.zeros((1,84,4),dtype=np.float32)
        output[0,:4,0]=[320,320,160,240];output[0,71,0]=.9
        output[0,:4,1]=[321,321,160,240];output[0,71,1]=.8
        output[0,:4,2]=[100,200,50,100];output[0,71,2]=.5;output[0,4,2]=.95
        output[0,:4,3]=[100,200,50,100];output[0,71,3]=.2
        phones=decode_phones(output,640,480,1.,0,80)
        self.assertEqual(len(phones),1)
        self.assertAlmostEqual(phones[0].x1,240/640)
        self.assertAlmostEqual(phones[0].y1,120/480)
        self.assertAlmostEqual(phones[0].y2,360/480)

    def test_empty_detection_is_empty_and_invalid_shape_is_rejected(self):
        self.assertEqual(decode_phones(np.zeros((1,84,10)),640,480,1.,0,80),())
        with self.assertRaises(ValueError):decode_phones(np.zeros((1,6,10)),640,480,1.,0,80)


if __name__=='__main__':unittest.main()
