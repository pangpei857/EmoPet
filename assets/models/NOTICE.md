# Local vision model sources

- Baseline object detector: Ultralytics YOLOv8s, COCO weights from
  https://huggingface.co/Ultralytics/YOLOv8/blob/main/yolov8s.pt
  exported locally with Ultralytics 8.3.162 to FP32 ONNX (640×640, opset 17).
  Outputs use COCO classes 0 (`person`) and 67 (`cell phone`).
- Experimental object detector: Ultralytics YOLO26s, official COCO weights from
  https://github.com/ultralytics/assets/releases/tag/v8.4.0
  exported with Ultralytics 8.4.218 to FP32 ONNX (640×640, opset 17).
  The one-to-many detection head emits raw boxes for class-specific CPU NMS.
  `ULTRALYTICS-LICENSE.txt` contains the upstream license for both detectors.
- Face landmarks and blendshapes: Google's MediaPipe Face Landmarker,
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- Hand landmarks: Google's MediaPipe Hand Landmarker,
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
- Body pose: Google's MediaPipe Pose Landmarker Lite,
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
- Alternative body pose: OpenMMLab RTMPose-s Body7 (COCO-17), the `end2end.onnx`
  from the official `rtmpose-s_simcc-body7_pt-body7_420e-256x192-acd4a1ef_20230504`
  SDK export in https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose.
  The SDK preprocessing parameters are applied by the app, and the OpenMMLab
  license is included as `MMPOSE-LICENSE.txt`.

Downloaded file hashes and byte counts are recorded in `manifest.json`.
Runtime packages retain their bundled license and metadata files in the complete
application folder. The vision models run locally from the packaged assets.
The vision pipeline does not download models or upload camera frames at runtime.

The hand/phone relationship and brow-change rules are heuristics. They do not
establish what a person is doing or diagnose a person's feelings or health.
Use one person in the frame and calibrate the neutral brow baseline if needed.

Reproduction: use the export environment described in the project README and
run `tools/prepare_vision_models.py --export-phone` for YOLOv8s or
`tools/prepare_vision_models.py --export-yolo26 --prepare-pose` for the trial
models. The packaged ONNX runtime does not require PyTorch or Ultralytics.
