"""Fit a clothing overlay to shoulder and torso landmarks."""
import math
import os
from pathlib import Path
import cv2
import numpy as np
from PIL import Image


def detect_shoulders(source):
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    model = Path(os.environ.get('POSE_MODEL_PATH', '/opt/models/pose_landmarker.task'))
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=.45,
        min_pose_presence_confidence=.45,
    )
    # White behind transparency avoids treating removed background as black clothing.
    rgb = Image.new('RGB', source.size, 'white')
    rgb.paste(source, mask=source.getchannel('A'))
    rgb.thumbnail((1200, 1200))
    with vision.PoseLandmarker.create_from_options(options) as detector:
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.array(rgb)))
    if not result.pose_landmarks:
        return None
    landmarks = result.pose_landmarks[0]
    shoulders = [landmarks[i] for i in (11, 12)]
    if any((point.visibility or 0) < .55 or (point.presence or 0) < .55 for point in shoulders):
        return None
    points = sorted([(p.x * source.width, p.y * source.height) for p in shoulders])
    left, right = np.array(points[0]), np.array(points[1])
    width = float(np.linalg.norm(right - left))
    if width < source.width * .08 or width > source.width * 1.2:
        return None
    if abs(math.degrees(math.atan2(*(right-left)[::-1]))) > 40:
        return None
    return left, right


def warp_suit(template, size, shoulders):
    left, right = [np.asarray(p, dtype=np.float32) for p in shoulders]
    mid = (left + right) / 2
    axis = right - left
    width = float(np.linalg.norm(axis))
    # Account for fabric beyond the shoulder joints, and preserve torso direction.
    left = mid - axis * .59
    right = mid + axis * .59
    down = np.array([-axis[1], axis[0]], dtype=np.float32) / width
    target = np.float32([left, right, mid + down * width * 1.20])
    sw, sh = template.size
    # Correspondences measured on the bundled front-facing suit asset.
    reference = np.float32([[sw*.16, sh*.36], [sw*.84, sh*.36], [sw*.50, sh*.94]])
    matrix = cv2.getAffineTransform(reference, target)
    rgba = np.array(template.convert('RGBA')).astype(np.float32) / 255
    rgba[:, :, :3] *= rgba[:, :, 3:4]
    output = cv2.warpAffine(rgba, matrix, size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)
    output = np.clip(output, 0, 1)
    output[:, :, :3] /= np.maximum(output[:, :, 3:4], 1e-6)
    return Image.fromarray((np.clip(output, 0, 1)*255).astype(np.uint8), 'RGBA')
