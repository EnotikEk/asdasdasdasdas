"""Local scratch repair using a damage mask and neighboring photo texture."""
import cv2
import numpy as np
from PIL import Image
from photo_retouch.processing.brush import apply_photo_edits


def restore_old_photo(source, strength=50, marks=None):
    strength = int(strength)
    if not 1 <= strength <= 100:
        raise ValueError('Сила реставрации должна быть от 1 до 100')
    rgb = np.array(source.convert('RGB'))
    height, width = rgb.shape[:2]
    factor = min(1., 1600 / max(width, height))
    small = cv2.resize(rgb, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    if marks:
        mask = 255 - np.array(apply_photo_edits(Image.new('RGBA', source.size, 'white'), marks).getchannel('A'))
    else:
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        bright = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
        candidates = np.uint8(bright > (38 - strength * .25)) * 255
        count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates, 8)
        mask_small = np.zeros_like(gray)
        min_length = max(12, max(gray.shape) * .025)
        for label in range(1, count):
            _, _, w, h, area = stats[label]
            length = max(w, h)
            fill = area / max(1, w*h)
            if length >= min_length and area >= 10 and (length / max(1, min(w, h)) > 3 or fill < .25):
                mask_small[labels == label] = 255
        mask_small = cv2.dilate(mask_small, np.ones((3, 3), np.uint8))
        mask = cv2.resize(mask_small, (width, height), interpolation=cv2.INTER_NEAREST)
    mask[np.array(source.getchannel('A')) == 0] = 0
    coverage = float(np.count_nonzero(mask)) / mask.size
    if coverage > .2:
        raise ValueError('Выделено слишком много повреждений. Уменьшите силу или отметьте царапины кистью.')
    repaired = cv2.inpaint(rgb, mask, max(2, min(9, 3 / factor)), cv2.INPAINT_TELEA) if np.any(mask) else rgb.copy()
    # Mild edge-preserving smoothing, without synthesizing new facial features.
    smooth = cv2.bilateralFilter(repaired, 5, 10 + strength * .15, 3)
    repaired = cv2.addWeighted(repaired, .7, smooth, .3, 0)
    result = Image.fromarray(repaired, 'RGB').convert('RGBA')
    result.putalpha(source.getchannel('A'))
    return result, round(coverage * 100, 2)
