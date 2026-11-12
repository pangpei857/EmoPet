import unittest
from types import SimpleNamespace
import numpy as np
from study_pet.vision import decode_phones,VisionEngine


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


class FaceFeatureExtractionTests(unittest.TestCase):
    def test_multiple_faces_keep_separate_full_blendshape_vectors(self):
        def landmarks(x):return [SimpleNamespace(x=x,y=.1),SimpleNamespace(x=x+.2,y=.4)]
        def scores(value):return [SimpleNamespace(category_name=name,score=value) for name in
            ('browDownLeft','browDownRight','jawOpen')]
        face_result=SimpleNamespace(face_landmarks=[landmarks(.1),landmarks(.6)],
            face_blendshapes=[scores(.1),scores(.9)])
        engine=VisionEngine.__new__(VisionEngine);engine._timestamp=-1
        engine.mp=SimpleNamespace(Image=lambda **kwargs:kwargs,ImageFormat=SimpleNamespace(SRGB=1))
        engine.face=SimpleNamespace(detect_for_video=lambda *args:face_result)
        engine.hand=SimpleNamespace(detect_for_video=lambda *args:SimpleNamespace(hand_landmarks=[]))
        _,o=engine.analyze_features(np.zeros((12,16,3),dtype=np.uint8),1.)
        self.assertEqual(len(o.face_features),2)
        self.assertEqual(tuple(f.box for f in o.face_features),o.faces)
        self.assertAlmostEqual(o.face_features[0].brow_score,.1)
        self.assertAlmostEqual(o.face_features[1].brow_score,.9)
        self.assertIn(('jawOpen',.9),o.face_features[1].blendshapes)
        self.assertFalse(o.brow_valid);self.assertEqual(o.brow_score,0.)


if __name__=='__main__':unittest.main()
