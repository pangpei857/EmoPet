"""CPU body pose for the single person found by the object detector."""
import math

import cv2
import numpy as np


RTMPOSE_FILE = 'rtmpose_s_body7.onnx'
MEDIAPIPE_POSE_FILE = 'pose_landmarker_lite.task'

_INPUT_WIDTH = 192
_INPUT_HEIGHT = 256
_PIXEL_MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
_PIXEL_STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)
_MEDIAPIPE_TO_COCO = (0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)


def _frame_point(x, y, score):
    if 0. <= x <= 1. and 0. <= y <= 1. and math.isfinite(score) and score > 0.:
        return float(x), float(y), min(1., float(score))
    return 0., 0., 0.


def _person_crop(person, width, height):
    x1, x2 = person.x1 * width, person.x2 * width
    y1, y2 = person.y1 * height, person.y2 * height
    if x2 - x1 < 16 or y2 - y1 < 16:
        return None
    return (x1+x2)/2, (y1+y2)/2, x2-x1, y2-y1


class RTMPoseBody:
    """OpenMMLab RTMPose-s Body7 ONNX using the model's SimCC decoder."""

    def __init__(self, model_path):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), sess_options=options,
                                            providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name

    def estimate(self, bgr, person):
        height, width = bgr.shape[:2]
        crop = _person_crop(person, width, height)
        if crop is None:
            return ()
        cx, cy, crop_width, crop_height = crop
        aspect = _INPUT_WIDTH / _INPUT_HEIGHT
        crop_width = max(crop_width, crop_height * aspect) * 1.25
        crop_height = crop_width / aspect
        scale_x, scale_y = _INPUT_WIDTH / crop_width, _INPUT_HEIGHT / crop_height
        transform = np.array([[scale_x, 0., _INPUT_WIDTH/2 - cx * scale_x],
                              [0., scale_y, _INPUT_HEIGHT/2 - cy * scale_y]], dtype=np.float32)
        crop_rgb = cv2.warpAffine(bgr, transform, (_INPUT_WIDTH, _INPUT_HEIGHT))[:, :, ::-1]
        normalized = (crop_rgb.astype(np.float32) - _PIXEL_MEAN) / _PIXEL_STD
        model_input = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])
        simcc_x, simcc_y = self.session.run(['simcc_x', 'simcc_y'], {self.input_name: model_input})
        if simcc_x.shape != (1, 17, 384) or simcc_y.shape != (1, 17, 512):
            raise ValueError('Unexpected RTMPose keypoint output')
        pixel_x = (simcc_x[0].argmax(axis=1) / 2 - _INPUT_WIDTH/2) / scale_x + cx
        pixel_y = (simcc_y[0].argmax(axis=1) / 2 - _INPUT_HEIGHT/2) / scale_y + cy
        scores = np.minimum(simcc_x[0].max(axis=1), simcc_y[0].max(axis=1))
        return tuple(_frame_point(x/width, y/height, score) for x, y, score in zip(pixel_x, pixel_y, scores))

    def close(self):
        self.session = None


class MediaPipeBody:
    """MediaPipe Pose Landmarker Lite, with its output mapped into COCO-17 order."""

    def __init__(self, model_path):
        import mediapipe as mp

        self.mp = mp
        vision = mp.tasks.vision
        options = vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
        )
        self.detector = vision.PoseLandmarker.create_from_options(options)

    def estimate(self, bgr, person):
        height, width = bgr.shape[:2]
        crop = _person_crop(person, width, height)
        if crop is None:
            return ()
        cx, cy, crop_width, crop_height = crop
        left, right = max(0, int(cx-.625*crop_width)), min(width, math.ceil(cx+.625*crop_width))
        top, bottom = max(0, int(cy-.625*crop_height)), min(height, math.ceil(cy+.625*crop_height))
        rgb = cv2.cvtColor(bgr[top:bottom, left:right], cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        poses = self.detector.detect(image).pose_landmarks
        if not poses or len(poses[0]) < 33:
            return ()
        points = []
        for index in _MEDIAPIPE_TO_COCO:
            landmark = poses[0][index]
            score = landmark.visibility if landmark.visibility is not None else 0.
            if landmark.presence is not None:
                score = min(score, landmark.presence)
            x = (left + landmark.x * (right-left)) / width
            y = (top + landmark.y * (bottom-top)) / height
            points.append(_frame_point(x, y, score))
        return tuple(points)

    def close(self):
        self.detector.close()
