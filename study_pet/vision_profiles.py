"""Local camera model choices shared by the settings UI and sensor process."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VisionProfile:
    label: str
    detector_file: str
    body_model: str | None = None


DEFAULT_VISION_PROFILE = 'yolov8s'
VISION_PROFILES = {
    DEFAULT_VISION_PROFILE: VisionProfile('YOLOv8s（原版）', 'phone_yolov8s.onnx'),
    'yolo26_mediapipe': VisionProfile('YOLO26s + MediaPipe Pose', 'phone_yolo26s.onnx', 'mediapipe'),
    'yolo26_rtmpose': VisionProfile('YOLO26s + RTMPose-s', 'phone_yolo26s.onnx', 'rtmpose'),
}

# Both body models are displayed in COCO-17 order. This threshold only controls
# the preview, because the two models' scores are not calibrated alike.
BODY_POINT_MIN_SCORE = .4
BODY_LINKS = ((0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (6, 8),
              (7, 9), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13),
              (12, 14), (13, 15), (14, 16))
