"""Non-destructive brush masks in normalized photo coordinates."""
import math
from PIL import Image, ImageChops, ImageDraw


def apply_photo_edits(image, strokes):
    if not strokes:
        return image
    if not isinstance(strokes, list) or len(strokes) > 1000:
        raise ValueError('Слишком много мазков: максимум 1000')
    mask = Image.new('L', image.size, 255)
    draw = ImageDraw.Draw(mask)
    for stroke in strokes:
        mode = stroke.get('mode')
        size = float(stroke.get('size', 0))
        points = stroke.get('points', [])
        if mode not in {'erase', 'restore'} or not math.isfinite(size) or not 0 < size <= 2:
            raise ValueError('Недопустимые параметры кисти')
        if not isinstance(points, list) or not 1 <= len(points) <= 10000:
            raise ValueError('Недопустимое количество точек мазка')
        coordinates = []
        for point in points:
            x, y = map(float, point)
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
                raise ValueError('Точка кисти за пределами фотографии')
            coordinates.append((round(x * (image.width-1)), round(y * (image.height-1))))
        diameter = max(1, round(size * min(image.size)))
        radius = diameter / 2
        color = 0 if mode == 'erase' else 255
        if len(coordinates) > 1:
            draw.line(coordinates, fill=color, width=diameter, joint='curve')
        for x, y in coordinates:
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
    result = image.copy()
    result.putalpha(ImageChops.multiply(image.getchannel('A'), mask))
    return result
