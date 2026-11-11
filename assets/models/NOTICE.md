# Local vision model sources

- Phone detector: Ultralytics YOLOv8s, COCO pretrained weights from
  https://huggingface.co/Ultralytics/YOLOv8/blob/main/yolov8s.pt
  exported locally with Ultralytics 8.3.162 to FP32 ONNX (640×640, opset 17).
  Only COCO class 67 (`cell phone`) is used. Upstream license text accompanies
  this directory in `ULTRALYTICS-LICENSE.txt`.
- Face landmarks and blendshapes: Google's MediaPipe Face Landmarker,
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- Hand landmarks: Google's MediaPipe Hand Landmarker,
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task

Downloaded file hashes and byte counts are recorded in `manifest.json`.
Runtime packages retain their bundled license and metadata files in the complete
application folder. The app performs local inference and has no model-download,
upload, microphone-recording or speech functionality at runtime.

The hand/phone relationship and brow-change rules are heuristics. They do not
establish what a person is doing or diagnose a person's feelings or health.
Use one person in the frame and calibrate the neutral brow baseline if needed.

Reproduction: install export-only dependencies in a separate development
environment and run `tools/prepare_vision_models.py --export-phone`. PyTorch and
Ultralytics are not required by the distributed ONNX inference application.
