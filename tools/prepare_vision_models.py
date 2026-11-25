"""Download upstream model assets; optionally export the phone detector to ONNX.

Run the export only in the separate development model-export environment.
The distributed application does not need PyTorch or network access.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
MODELS=ROOT/'assets'/'models'
SOURCES={
    'face_landmarker.task':'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
    'hand_landmarker.task':'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
    'yamnet.tflite':'https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite',
}
PURPOSES={
    'phone_yolov8s.onnx':'COCO person class 0 and cell phone class 67, FP32 ONNX 640',
    'phone_yolo26s.onnx':'COCO person class 0 and cell phone class 67, one-to-many FP32 ONNX 640',
    'pose_landmarker_lite.task':'MediaPipe Pose Landmarker Lite, body keypoints',
    'rtmpose_s_body7.onnx':'OpenMMLab RTMPose-s Body7, COCO-17 SimCC keypoints, FP32 ONNX 192x256',
    'yamnet.tflite':'MediaPipe Audio Classifier, experimental local sigh candidates',
}
WEIGHTS='https://huggingface.co/Ultralytics/YOLOv8/resolve/main/yolov8s.pt'
YOLO26_WEIGHTS = 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt'
YOLO26_CHECKPOINT_HASH = '646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b'
MEDIAPIPE_POSE = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task'
RTMPOSE_SDK = ('https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/'
              'rtmpose-s_simcc-body7_pt-body7_420e-256x192-acd4a1ef_20230504.zip')
MMPOSE_LICENSE = 'https://raw.githubusercontent.com/open-mmlab/mmpose/v1.3.2/LICENSE'
PROVENANCE = {**SOURCES, 'phone_yolov8s.onnx': WEIGHTS, 'phone_yolo26s.onnx': YOLO26_WEIGHTS,
              'pose_landmarker_lite.task': MEDIAPIPE_POSE, 'rtmpose_s_body7.onnx': RTMPOSE_SDK}

def download(url,destination):
    if destination.exists() and destination.stat().st_size>100000:return
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix(destination.suffix+'.download')
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Python-urllib/3.12'})
            with urllib.request.urlopen(request,timeout=45) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response,output)
            temporary.replace(destination);return
        except Exception:
            if attempt==2:raise
            time.sleep(1)

def verify_digest(content, expected, name):
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError(f'Unexpected SHA-256 for {name}')


def export_yolo26():
    weights = ROOT/'.artifacts'/'yolo26s.pt'
    download(YOLO26_WEIGHTS, weights)
    verify_digest(weights.read_bytes(), YOLO26_CHECKPOINT_HASH, weights.name)
    import onnx
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(2)
    model = YOLO(str(weights))
    exported = model.export(format='onnx', imgsz=640, opset=17, simplify=False,
                            dynamic=False, nms=None, device='cpu')
    output = onnx.load(exported, load_external_data=False).graph.output[0]
    shape = tuple(dim.dim_value for dim in output.type.tensor_type.shape.dim)
    if shape != (1, 84, 8400):
        raise RuntimeError(f'Expected raw YOLO26 output, got {shape}. Use Ultralytics 8.4.218.')
    shutil.copy2(exported, MODELS/'phone_yolo26s.onnx')


def prepare_pose():
    cache = ROOT/'.artifacts'
    media = cache/'pose_landmarker_lite.task'
    download(MEDIAPIPE_POSE, media)
    verify_digest(media.read_bytes(), '59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a', media.name)
    shutil.copy2(media, MODELS/media.name)

    archive = cache/'rtmpose-s-body7-official.zip'
    download(RTMPOSE_SDK, archive)
    verify_digest(archive.read_bytes(), '7673922e531014906ca4f0f239b7e233b740146a10b632deaa2a28d45470d802', archive.name)
    with ZipFile(archive) as package:
        [member] = [name for name in package.namelist() if name.endswith('/end2end.onnx')]
        onnx = package.read(member)
    verify_digest(onnx, '9aeb635b83f86aea45cf45d85798f7eba1a162de8e0d721c44e54fe5eebaf47d', 'RTMPose ONNX')
    (MODELS/'rtmpose_s_body7.onnx').write_bytes(onnx)

    license_path = MODELS/'MMPOSE-LICENSE.txt'
    if not license_path.is_file():
        download(MMPOSE_LICENSE, license_path)


def write_manifest():
    records=[]
    for path in sorted(MODELS.iterdir()):
        if path.name in PROVENANCE:
            records.append({'file':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                            'source':PROVENANCE[path.name],'purpose':PURPOSES.get(path.name,'MediaPipe CPU landmarks')})
    (MODELS/'manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--export-phone',action='store_true',help='Export the original YOLOv8s baseline')
    parser.add_argument('--export-yolo26',action='store_true',help='Export the raw YOLO26s one-to-many detector')
    parser.add_argument('--prepare-pose',action='store_true',help='Prepare the two body pose models')
    args=parser.parse_args()
    for name,url in SOURCES.items():
        download(url,MODELS/name);print('READY',name,flush=True)
    if args.export_phone:
        weights=ROOT/'.artifacts'/'yolov8s.pt';download(WEIGHTS,weights)
        # Upstream Hugging Face LFS identity for this exact checkpoint.
        expected='268e5bb54c640c96c3510224833bc2eeacab4135c6deb41502156e39986b562d'
        if hashlib.sha256(weights.read_bytes()).hexdigest()!=expected:raise RuntimeError('Unexpected upstream YOLO checkpoint hash')
        from ultralytics import YOLO
        exported=YOLO(str(weights)).export(format='onnx',imgsz=640,opset=17,simplify=False,dynamic=False,device='cpu')
        shutil.copy2(exported,MODELS/'phone_yolov8s.onnx')
    if args.export_yolo26:export_yolo26()
    if args.prepare_pose:prepare_pose()
    write_manifest()
    print('READY model manifest',flush=True)

if __name__=='__main__':main()
