import unittest
from types import SimpleNamespace
import numpy as np
from study_pet.vision import decode_phones,decode_persons,face_measurements,VisionEngine
from study_pet.perception import Box,FaceFeatures,Observation,VisionSettings
from study_pet.vision_behavior import head_down


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

    def test_person_and_phone_are_decoded_from_same_output_with_separate_suppression(self):
        output=np.zeros((1,84,3),dtype=np.float32)
        output[0,:4,:]=np.array([[320,320,150],[320,320,200],[160,160,100],[240,240,240]])
        output[0,4,0]=.95;output[0,71,1]=.9
        output[0,4,2]=.6;output[0,5,2]=.99
        people=decode_persons(output,640,480,1.,0,80)
        phones=decode_phones(output,640,480,1.,0,80)
        self.assertEqual(len(people),1);self.assertEqual(len(phones),1)
        self.assertEqual(people[0].x1,phones[0].x1)


class FaceFeatureExtractionTests(unittest.TestCase):
    def test_positive_canonical_x_rotation_is_relative_head_lowering(self):
        # Canonical +Y is up and +Z is the outward facial normal. A positive
        # X rotation tilts that normal down; the inferred pitch must agree.
        angle=np.deg2rad(25.)
        rotation=np.array([[1,0,0],[0,np.cos(angle),-np.sin(angle)],[0,np.sin(angle),np.cos(angle)]])
        self.assertLess((rotation@np.array([0.,0.,1.]))[1],0.)
        matrix=np.eye(4);matrix[:3,:3]=rotation
        landmarks=[SimpleNamespace(x=.5,y=.5,z=0.) for _ in range(478)]
        for index,x in ((263,.63),(362,.56),(133,.44),(33,.37)):landmarks[index].x=x
        image=np.random.default_rng(1).integers(0,255,(256,256,3),dtype=np.uint8)
        box=Box(.2,.1,.8,.8)
        values=face_measurements(landmarks,matrix,image,box)
        self.assertAlmostEqual(values['pitch'],25.)
        feature=FaceFeatures(box,(('browDownLeft',.1),('browDownRight',.1)),**values)
        observation=Observation(0.,faces=(box,),face_features=(feature,))
        self.assertTrue(head_down(observation,VisionSettings(neutral_yaw=0.,neutral_pitch=0.)))

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
