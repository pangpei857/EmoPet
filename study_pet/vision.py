"""Local CPU vision. Imported in the sensor process, never by the pet painter."""
from pathlib import Path
from dataclasses import replace
import time

import cv2
import numpy as np

from .perception import Box, FaceFeatures, Observation

MODEL_DIR=Path(__file__).resolve().parents[1]/'assets'/'models'


def _decode_class(output,width,height,ratio,pad_x,pad_y,category,threshold):
    rows=np.asarray(output)[0]
    if rows.shape[0]!=84:raise ValueError('Unexpected phone detector output')
    rows=rows.T
    scores=rows[:,4+category]
    # A different class must not be promoted to 'phone' merely because its
    # phone score also exceeds the threshold.
    selected=(scores>=threshold)&(rows[:,4:].argmax(axis=1)==category)
    boxes=[];confidences=[]
    for row,score in zip(rows[selected],scores[selected]):
        cx,cy,w,h=map(float,row[:4])
        x1=max(0.,min(float(width),(cx-w/2-pad_x)/ratio))
        y1=max(0.,min(float(height),(cy-h/2-pad_y)/ratio))
        x2=max(0.,min(float(width),(cx+w/2-pad_x)/ratio))
        y2=max(0.,min(float(height),(cy+h/2-pad_y)/ratio))
        if x2-x1<5 or y2-y1<8:continue
        boxes.append([x1,y1,x2-x1,y2-y1]);confidences.append(float(score))
    if not boxes:return ()
    keep=cv2.dnn.NMSBoxes(boxes,confidences,threshold,.45)
    return tuple(Box(boxes[i][0]/width,boxes[i][1]/height,
                     (boxes[i][0]+boxes[i][2])/width,(boxes[i][1]+boxes[i][3])/height,confidences[i])
                 for i in np.asarray(keep).reshape(-1))


def decode_phones(output,width,height,ratio,pad_x,pad_y,threshold=.38):
    return _decode_class(output,width,height,ratio,pad_x,pad_y,67,threshold)


def decode_persons(output,width,height,ratio,pad_x,pad_y,threshold=.45):
    """Person boxes assist occupancy, never identity or liveness verification."""
    return _decode_class(output,width,height,ratio,pad_x,pad_y,0,threshold)


class PhoneDetector:
    def __init__(self,path=MODEL_DIR/'phone_yolov8s.onnx'):
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        input_info=self.session.get_inputs()[0]
        self.input_name=input_info.name;self.size=int(input_info.shape[2])

    def detect(self,bgr):
        return self.detect_objects(bgr)[0]

    def detect_objects(self,bgr):
        h,w=bgr.shape[:2];ratio=min(self.size/w,self.size/h)
        nw,nh=round(w*ratio),round(h*ratio)
        left,top=(self.size-nw)//2,(self.size-nh)//2
        image=np.full((self.size,self.size,3),114,dtype=np.uint8)
        image[top:top+nh,left:left+nw]=cv2.resize(bgr,(nw,nh),interpolation=cv2.INTER_LINEAR)
        tensor=np.ascontiguousarray(image[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255.
        output=self.session.run(None,{self.input_name:tensor})[0]
        return (decode_phones(output,w,h,ratio,left,top),decode_persons(output,w,h,ratio,left,top))


def face_measurements(landmarks,matrix,bgr,box):
    """Scalar quality/pose summaries only; raw landmarks are not persisted."""
    height,width=bgr.shape[:2]
    if len(landmarks)<387:
        return dict(quality_ok=False,quality_reason='面部关键点不完整')
    yaw=pitch=roll=None
    if matrix is not None:
        rotation=np.asarray(matrix,dtype=np.float64)[:3,:3].copy()
        norms=np.linalg.norm(rotation,axis=0)
        if np.all(norms>1e-6):
            rotation/=norms
            angles=cv2.RQDecomp3x3(rotation)[0]
            # Camera coordinates have downward y; relative x rotation is a
            # pitch signal. A neutral side-view is calibrated by the user.
            pitch,yaw,roll=(float(v) for v in angles)
            pitch=(pitch+180)%360-180
    left=abs(landmarks[263].x-landmarks[362].x)
    right=abs(landmarks[133].x-landmarks[33].x)
    def distance(i,j):
        a=landmarks[i];b=landmarks[j]
        return float(np.linalg.norm([a.x-b.x,(a.y-b.y)*height/width,a.z-b.z]))
    left_geo=distance(334,386)/max(.005,distance(263,362))
    right_geo=distance(105,159)/max(.005,distance(33,133))
    geometry=(left_geo*left+right_geo*right)/max(.001,left+right)
    x1=max(0,int(box.x1*width));x2=min(width,int(box.x2*width))
    y1=max(0,int(box.y1*height));y2=min(height,int(box.y2*height))
    crop=bgr[y1:y2,x1:x2]
    reason=''
    if crop.size==0 or x2-x1<48 or y2-y1<60:reason='面部太小，请调整距离'
    else:
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        brightness=float(gray.mean());sharpness=float(cv2.Laplacian(gray,cv2.CV_64F).var())
        if not 25<=brightness<=235:reason='面部光线不足或过曝'
        elif sharpness<12:reason='眉眼画面模糊'
        elif yaw is None or pitch is None:reason='头部角度暂不可用'
        elif abs(yaw)>72 or abs(pitch)>65 or max(left,right)<.012:reason='侧转或遮挡过大，眉眼信息不足'
    return dict(yaw=yaw,pitch=pitch,roll=roll,quality_ok=not reason,quality_reason=reason,
        brow_geometry=geometry,left_visibility=left,right_visibility=right)


class VisionEngine:
    def __init__(self,model_dir=MODEL_DIR,include_phone=True):
        import mediapipe as mp
        self.mp=mp;self.face=None;self.hand=None;self.phone=None;self.warnings=[]
        cv2.setNumThreads(2)
        for name,label in [('phone_yolov8s.onnx','手机检测'),('face_landmarker.task','面部检测'),('hand_landmarker.task','手部检测')]:
            if not (model_dir/name).is_file():raise FileNotFoundError(f'{label}模型缺失，请重新安装完整的应用文件夹。')
        # Read model buffers so MediaPipe can run from Chinese Windows paths.
        base=mp.tasks.BaseOptions;vision=mp.tasks.vision
        try:
            if include_phone:self.phone=PhoneDetector(model_dir/'phone_yolov8s.onnx')
            self.face=vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=base(model_asset_buffer=(model_dir/'face_landmarker.task').read_bytes()),
                running_mode=vision.RunningMode.VIDEO,num_faces=2,output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                min_face_detection_confidence=.55,min_face_presence_confidence=.55,min_tracking_confidence=.5))
            self.hand=vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=base(model_asset_buffer=(model_dir/'hand_landmarker.task').read_bytes()),
                running_mode=vision.RunningMode.VIDEO,num_hands=2,
                min_hand_detection_confidence=.5,min_hand_presence_confidence=.5,min_tracking_confidence=.5))
        except Exception:
            self.close();raise
        self._timestamp=-1

    def analyze(self,bgr,timestamp=None):
        started=time.monotonic();now=started if timestamp is None else timestamp
        phones,persons=self.phone.detect_objects(bgr) if self.phone is not None else ((),())
        phone_ms=(time.monotonic()-started)*1000
        rgb,observation=self.analyze_features(bgr,now)
        return rgb,replace(observation,phones=phones,persons=persons,person_fresh=self.phone is not None,phone_ms=phone_ms,
            inference_ms=(time.monotonic()-started)*1000)

    def analyze_features(self,bgr,timestamp=None):
        """Face and hand tracking never waits for the phone model."""
        started=time.monotonic();now=started if timestamp is None else timestamp
        stamp=max(self._timestamp+1,int(now*1000));self._timestamp=stamp
        rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
        image=self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb)
        face_started=time.monotonic()
        faces=self.face.detect_for_video(image,stamp)
        face_ms=(time.monotonic()-face_started)*1000
        hand_started=time.monotonic()
        hands=self.hand.detect_for_video(image,stamp)
        hand_ms=(time.monotonic()-hand_started)*1000
        face_boxes=[];features=[]
        for index,landmarks in enumerate(faces.face_landmarks):
            xs=[p.x for p in landmarks];ys=[p.y for p in landmarks]
            face_boxes.append(Box(max(0.,min(xs)),max(0.,min(ys)),min(1.,max(xs)),min(1.,max(ys))))
            categories=faces.face_blendshapes[index] if index<len(faces.face_blendshapes) else ()
            matrices=getattr(faces,'facial_transformation_matrixes',())
            measurements=face_measurements(landmarks,matrices[index] if index<len(matrices) else None,bgr,face_boxes[-1])
            features.append(FaceFeatures(face_boxes[-1],tuple((item.category_name,float(item.score)) for item in categories),**measurements))
        single=features[0] if len(features)==1 else None
        score=single.brow_score if single is not None else 0.
        down=single.eyes_down if single is not None else 0.
        hand_points=tuple(tuple((p.x,p.y) for p in hand) for hand in hands.hand_landmarks)
        return rgb,Observation(now,(),hand_points,tuple(face_boxes),score,down,
            (time.monotonic()-started)*1000,face_ms=face_ms,hand_ms=hand_ms,
            face_features=tuple(features),brow_valid=single is not None and single.brow_valid,
            frame_ok=15<float(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY).mean())<245)

    def close(self):
        for detector in (self.face,self.hand):
            if detector is not None:detector.close()
        self.face=None;self.hand=None;self.phone=None

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
