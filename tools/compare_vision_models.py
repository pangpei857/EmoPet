"""Compare the shipped CPU models on a fixed slice of COCO val2017.

Run from the project root with ``python -m tools.compare_vision_models``.
The annotations are the official instances and person_keypoints JSON files.
Only ``--download-images`` retrieves public images; it is never called by Momo.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import random
import statistics
import time
from urllib.request import urlopen

import cv2
import numpy as np

from study_pet.body_pose import MEDIAPIPE_POSE_FILE, RTMPOSE_FILE, MediaPipeBody, RTMPoseBody
from study_pet.face_tracking import area, overlap
from study_pet.perception import Box
from study_pet.vision import MODEL_DIR, PERSON_MIN_SCORE, PHONE_MIN_SCORE, PhoneDetector
from study_pet.vision_profiles import BODY_POINT_MIN_SCORE


COCO_IMAGES = 'https://s3.amazonaws.com/images.cocodataset.org/val2017/'
SOURCE_ANNOTATIONS = 'https://images.cocodataset.org/annotations/annotations_trainval2017.zip'
PERSON, PHONE = 1, 77  # COCO JSON IDs, distinct from model channel indices.
PER_GROUP, SEED = 24, 26
VALIDATION_DIR = Path('.artifacts/vision-coco-val')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def select_examples(annotation_dir):
    instances = read_json(annotation_dir/'instances_val2017.json')
    by_image, crowd = defaultdict(lambda: defaultdict(list)), set()
    for record in instances['annotations']:
        if record['category_id'] not in {PERSON, PHONE}:
            continue
        image_id = record['image_id']
        if record['iscrowd']:
            crowd.add(image_id)
        else:
            by_image[image_id][record['category_id']].append(record)
    images = {item['id']: item for item in instances['images'] if item['id'] not in crowd}
    del instances
    rng = random.Random(SEED)
    phone_yes = rng.sample(sorted(i for i in images if by_image[i][PHONE]), PER_GROUP)
    phone_no = rng.sample(sorted(i for i in images if not by_image[i][PHONE]), PER_GROUP)
    selected = set(phone_yes + phone_no)
    keypoints = read_json(annotation_dir/'person_keypoints_val2017.json')['annotations']
    eligible_poses = {
        record['image_id']: record for record in keypoints
        if record['image_id'] in images and record['image_id'] not in selected
        and not record['iscrowd'] and len(by_image[record['image_id']][PERSON]) == 1
        and sum(v == 2 for v in record['keypoints'][2::3]) >= 10
        and record['bbox'][2] >= 80 and record['bbox'][3] >= 100
    }
    pose_ids = rng.sample(sorted(eligible_poses), PER_GROUP)
    return [(images[i], by_image[i], eligible_poses.get(i) if i in pose_ids else None)
            for i in sorted(selected.union(pose_ids))]


def load_image(path, download):
    if not path.is_file() and download:
        for attempt in range(3):
            try:
                with urlopen(COCO_IMAGES+path.name, timeout=12) as response:
                    data = response.read(10_000_001)
                if not data.startswith(b'\xff\xd8') or len(data) > 10_000_000:
                    raise ValueError('Expected a COCO JPEG')
                path.write_bytes(data)
                break
            except (OSError, ValueError):
                if attempt == 2:
                    raise
    image = cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Invalid COCO image {path}')
    h, w = image.shape[:2]
    scale = min(1., 960/w, 720/h)
    if scale < 1.:
        image = cv2.resize(image, (round(w*scale),round(h*scale)))
    return image


def truth_box(record, metadata):
    x, y, w, h = record['bbox']
    width, height = metadata['width'], metadata['height']
    return Box(max(0.,x/width),max(0.,y/height),min(1.,(x+w)/width),min(1.,(y+h)/height))


def box_iou(first, second):
    intersection = overlap(first, second)
    return intersection / max(1e-9, area(first)+area(second)-intersection)


def count_matches(predictions, targets):
    remaining = list(targets)
    hits = 0
    for prediction in sorted(predictions, key=lambda box: box.score, reverse=True):
        if not remaining:
            break
        index = max(range(len(remaining)), key=lambda i: box_iou(prediction, remaining[i]))
        if box_iou(prediction, remaining[index]) >= .5:
            hits += 1
            del remaining[index]
    return hits


def latency(elapsed):
    return {'median_ms': round(statistics.median(elapsed),2), 'p95_ms': round(float(np.percentile(elapsed,95)),2)}


def evaluate_detector(path, examples, frames):
    detector = PhoneDetector(path)
    for frame in frames[:3]:
        detector.detect_objects(frame)
    result = {'phone': [0,0,0], 'person': [0,0,0]}
    elapsed, pose_examples = [], []
    for (metadata, labels, pose_label), frame in zip(examples, frames):
        start = time.perf_counter()
        phones, people = detector.detect_objects(frame)
        elapsed.append((time.perf_counter()-start)*1000)
        for name, boxes, id_ in (('phone',phones,PHONE),('person',people,PERSON)):
            truth = [truth_box(record,metadata) for record in labels[id_]]
            result[name][0] += count_matches(boxes,truth)
            result[name][1] += len(boxes)
            result[name][2] += len(truth)
        if pose_label and len(people) == 1 and box_iou(people[0],truth_box(pose_label,metadata)) >= .5:
            pose_examples.append((frame, people[0], metadata, pose_label))
    report = {name: {'matched':tp, 'predictions':predicted, 'labels':expected,
                     'precision':round(tp/max(1,predicted),4), 'recall':round(tp/max(1,expected),4)}
              for name,(tp,predicted,expected) in result.items()}
    return {**report, **latency(elapsed)}, pose_examples


def evaluate_pose(estimator, examples):
    for image, person, _, _ in examples[:3]:
        estimator.estimate(image,person)
    correct = total = with_points = 0
    elapsed = []
    for frame, person, metadata, label in examples:
        start = time.perf_counter()
        points = estimator.estimate(frame,person)
        elapsed.append((time.perf_counter()-start)*1000)
        width, height = metadata['width'], metadata['height']
        tolerance = .1 * max(label['bbox'][2:])
        with_points += sum(score>=BODY_POINT_MIN_SCORE for _,_,score in points) >= 4
        for i in range(17):
            x, y, visible = label['keypoints'][3*i:3*i+3]
            if visible != 2:
                continue
            total += 1
            if points:
                px, py, score = points[i]
                correct += score>=BODY_POINT_MIN_SCORE and math.hypot(px*width-x,py*height-y)<=tolerance
    return {'examples':len(examples), 'with_at_least_four_visible_points':with_points,
            'visible_labeled_points':total,'correct_points':correct,
            'visible_pck_at_0_1':round(correct/max(1,total),4), **latency(elapsed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotation-dir', type=Path, default=VALIDATION_DIR)
    parser.add_argument('--image-dir', type=Path, default=VALIDATION_DIR/'images')
    parser.add_argument('--output', type=Path, default=VALIDATION_DIR/'comparison.json')
    parser.add_argument('--download-images', action='store_true')
    parser.add_argument('--nms-free-model', type=Path, help='Optional YOLO26 one-to-one ONNX control')
    args = parser.parse_args()
    cv2.setNumThreads(2)
    examples = select_examples(args.annotation_dir)
    args.image_dir.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = list(pool.map(lambda sample: load_image(args.image_dir/sample[0]['file_name'],args.download_images),examples))
    print(f'Loaded {len(frames)} COCO val2017 images',flush=True)
    detectors = [('YOLOv8s',MODEL_DIR/'phone_yolov8s.onnx'),('YOLO26s',MODEL_DIR/'phone_yolo26s.onnx')]
    if args.nms_free_model:
        detectors.append(('YOLO26s NMS-free',args.nms_free_model))
    report = {'source':SOURCE_ANNOTATIONS,'sample_seed':SEED,'images':len(frames),
              'image_ids':[metadata['id'] for metadata,_,_ in examples],
              'phone_threshold':PHONE_MIN_SCORE,'person_threshold':PERSON_MIN_SCORE,'match_iou':.5,
              'body_point_threshold':BODY_POINT_MIN_SCORE,'body_annotation_examples':PER_GROUP,
              'box_results':{}, 'body_results':{}}
    for name, path in detectors:
        metrics, crops = evaluate_detector(path,examples,frames)
        report['box_results'][name] = metrics
        print(name,json.dumps(metrics),flush=True)
        if name == 'YOLO26s':
            pose_examples = crops
    if not pose_examples:
        raise RuntimeError('No matching singleton YOLO26 human crop for pose evaluation')
    for name, estimator_type, filename in (('MediaPipe Pose Lite',MediaPipeBody,MEDIAPIPE_POSE_FILE),
                                            ('RTMPose-s Body7',RTMPoseBody,RTMPOSE_FILE)):
        estimator = estimator_type(MODEL_DIR/filename)
        try:
            metrics = evaluate_pose(estimator,pose_examples)
        finally:
            estimator.close()
        report['body_results'][name] = metrics
        print(name,json.dumps(metrics),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
