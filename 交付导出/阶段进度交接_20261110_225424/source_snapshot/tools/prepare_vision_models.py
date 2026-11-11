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

ROOT=Path(__file__).resolve().parents[1]
MODELS=ROOT/'assets'/'models'
SOURCES={
    'face_landmarker.task':'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
    'hand_landmarker.task':'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
}
WEIGHTS='https://huggingface.co/Ultralytics/YOLOv8/resolve/main/yolov8n.pt'

def download(url,destination):
    if destination.exists() and destination.stat().st_size>100000:return
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix(destination.suffix+'.download')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=45) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response,output)
            temporary.replace(destination);return
        except Exception:
            if attempt==2:raise
            time.sleep(1)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--export-phone',action='store_true');args=parser.parse_args()
    for name,url in SOURCES.items():
        download(url,MODELS/name);print('READY',name,flush=True)
    if args.export_phone:
        weights=ROOT/'.artifacts'/'yolov8n.pt';download(WEIGHTS,weights)
        # Upstream Hugging Face LFS identity for this exact checkpoint.
        expected='31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95'
        if hashlib.sha256(weights.read_bytes()).hexdigest()!=expected:raise RuntimeError('Unexpected upstream YOLO checkpoint hash')
        from ultralytics import YOLO
        exported=YOLO(str(weights)).export(format='onnx',imgsz=640,opset=17,simplify=False,dynamic=False,device='cpu')
        shutil.copy2(exported,MODELS/'phone_yolov8n.onnx')
    records=[]
    for path in sorted(MODELS.iterdir()):
        if path.suffix in {'.task','.onnx'}:
            records.append({'file':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                            'source':SOURCES.get(path.name,WEIGHTS),'purpose':'COCO cell phone class 67, exported FP32 ONNX 640' if path.suffix=='.onnx' else 'MediaPipe CPU landmarks'})
    (MODELS/'manifest.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print('READY model manifest',flush=True)

if __name__=='__main__':main()
