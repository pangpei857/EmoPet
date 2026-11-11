"""Local CPU vision. Imported in the sensor process, never by the pet painter."""
from pathlib import Path
import time

import cv2
import numpy as np

from .perception import Box, Observation

MODEL_DIR=Path(__file__).resolve().parents[1]/'assets'/'models'


def decode_phones(output,width,height,ratio,pad_x,pad_y,threshold=.38):
    """Decode the pinned YOLOv8 COCO ONNX output, then suppress duplicate boxes."""
    rows=np.asarray(output)[0]
    if rows.shape[0]!=84:raise ValueError('Unexpected phone detector output')
    rows=rows.T
    scores=rows[:,4+67]
    # A different class must not be promoted to 'phone' merely because its
    # phone score also exceeds the threshold.
    selected=(scores>=threshold)&(rows[:,4:].argmax(axis=1)==67)
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


class PhoneDetector:
    def __init__(self,path=MODEL_DIR/'phone_yolov8s.onnx'):
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        input_info=self.session.get_inputs()[0]
        self.input_name=input_info.name;self.size=int(input_info.shape[2])

    def detect(self,bgr):
        h,w=bgr.shape[:2];ratio=min(self.size/w,self.size/h)
        nw,nh=round(w*ratio),round(h*ratio)
        left,top=(self.size-nw)//2,(self.size-nh)//2
        image=np.full((self.size,self.size,3),114,dtype=np.uint8)
        image[top:top+nh,left:left+nw]=cv2.resize(bgr,(nw,nh),interpolation=cv2.INTER_LINEAR)
        tensor=np.ascontiguousarray(image[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255.
        output=self.session.run(None,{self.input_name:tensor})[0]
        return decode_phones(output,w,h,ratio,left,top)


class VisionEngine:
    def __init__(self,model_dir=MODEL_DIR):
        import mediapipe as mp
        self.mp=mp;self.face=None;self.hand=None;self.phone=None;self.warnings=[]
        cv2.setNumThreads(2)
        for name,label in [('phone_yolov8s.onnx','手机检测'),('face_landmarker.task','面部检测'),('hand_landmarker.task','手部检测')]:
            if not (model_dir/name).is_file():raise FileNotFoundError(f'{label}模型缺失，请重新安装完整的应用文件夹。')
        # Read model buffers so MediaPipe can run from Chinese Windows paths.
        base=mp.tasks.BaseOptions;vision=mp.tasks.vision
        try:
            self.phone=PhoneDetector(model_dir/'phone_yolov8s.onnx')
            self.face=vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=base(model_asset_buffer=(model_dir/'face_landmarker.task').read_bytes()),
                running_mode=vision.RunningMode.VIDEO,num_faces=2,output_face_blendshapes=True,
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
        stamp=max(self._timestamp+1,int(now*1000));self._timestamp=stamp
        phones=self.phone.detect(bgr)
        rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
        image=self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb)
        faces=self.face.detect_for_video(image,stamp)
        hands=self.hand.detect_for_video(image,stamp)
        face_boxes=[]
        for landmarks in faces.face_landmarks:
            xs=[p.x for p in landmarks];ys=[p.y for p in landmarks]
            face_boxes.append(Box(max(0.,min(xs)),max(0.,min(ys)),min(1.,max(xs)),min(1.,max(ys))))
        score=down=0.
        if len(face_boxes)==1 and faces.face_blendshapes:
            values={item.category_name:item.score for item in faces.face_blendshapes[0]}
            score=(values.get('browDownLeft',0.)+values.get('browDownRight',0.))/2
            down=(values.get('eyeLookDownLeft',0.)+values.get('eyeLookDownRight',0.))/2
        hand_points=tuple(tuple((p.x,p.y) for p in hand) for hand in hands.hand_landmarks)
        return rgb,Observation(now,phones,hand_points,tuple(face_boxes),score,down,(time.monotonic()-started)*1000)

    def close(self):
        for detector in (self.face,self.hand):
            if detector is not None:detector.close()
        self.face=None;self.hand=None;self.phone=None

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
