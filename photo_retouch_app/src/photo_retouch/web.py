"""Flask interface for the photo editor; project state travels with each render."""
import io
import json
import os
from pathlib import Path
from uuid import uuid4
from functools import lru_cache

from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from photo_retouch.core.models import Project, ASSET_CATEGORIES
from photo_retouch.processing.engine import Compositor, ImageProcessor, TextRenderer
from photo_retouch.processing.brush import apply_photo_edits


@lru_cache(maxsize=1)
def background_session():
    from rembg import new_session
    return new_session('u2netp', providers=['CPUExecutionProvider'])


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024
    root = Path(data_dir or os.environ.get('PHOTO_RETOUCH_DATA', 'PhotoRetouchProject')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in ASSET_CATEGORIES.values():
        (root / folder).mkdir(exist_ok=True)

    def asset_path(value):
        path = (root / value).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Ресурс не найден или путь недопустим')
        return path

    def image(value):
        with Image.open(asset_path(value)) as source:
            return ImageOps.exif_transpose(source).convert('RGBA')

    def render(state):
        project = Project.from_dict(state)
        photo = project.restored_photo or project.initial_photo
        size = image(photo).size if photo else (1024, 1024)
        if size[0] * size[1] > 32_000_000:
            raise ValueError('Изображение слишком большое (максимум 32 Мп)')
        compositor = Compositor(size)
        if project.background:
            compositor.set_layer_image('background', image(project.background))
        if photo:
            adjusted = ImageProcessor.apply_adjustments(image(photo), project.adjustments)
            compositor.set_layer_image('photo', apply_photo_edits(adjusted, state.get('photoEdits', {}).get(photo, [])))
        if project.costume:
            compositor.set_layer_image('costume', image(project.costume), project.costume_transform)
        if project.frame:
            compositor.set_layer_image('frame', image(project.frame))
        font = project.font or project.text_overlay.font_path
        compositor.set_layer_image('text', TextRenderer.render_text(project.text_overlay, size, str(asset_path(font)) if font else ''))
        for name, visible in project.layer_visibility.items():
            compositor.set_layer_visibility(name, visible)
        compositor.set_layer_opacity('costume', max(0, min(1, float(state.get('costumeOpacity', 1)))))
        order = state.get('layerOrder', Compositor.LAYER_ORDER)
        if sorted(order) != sorted(Compositor.LAYER_ORDER):
            raise ValueError('Недопустимый порядок слоёв')
        compositor.LAYER_ORDER = order
        return compositor.composite()

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, (ValueError, TypeError, KeyError, UnidentifiedImageError, Image.DecompressionBombError)):
            return jsonify(error=str(exc)), 400
        app.logger.exception('Request failed')
        return jsonify(error='Не удалось обработать запрос'), 500

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    @app.get('/api/ai-status')
    def ai_status():
        return jsonify(configured=bool(os.environ.get('OPENAI_API_KEY', '').strip()))

    @app.get('/api/assets')
    def assets():
        return jsonify({key: [f'{folder}/{p.name}' for p in sorted((root / folder).iterdir()) if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.ttf', '.otf'}] for key, folder in ASSET_CATEGORIES.items()})

    @app.post('/api/upload/<category>')
    def upload(category):
        if category not in ASSET_CATEGORIES:
            raise ValueError('Неизвестная категория')
        file = request.files['file']
        name = secure_filename(file.filename or '')
        suffix = Path(name).suffix.lower()
        if category == 'fonts':
            if suffix not in {'.ttf', '.otf'}:
                raise ValueError('Нужен файл TTF или OTF')
            from fontTools.ttLib import TTFont
            TTFont(io.BytesIO(file.read())).close()
            file.seek(0)
        else:
            with Image.open(file.stream) as img:
                if img.width * img.height > 32_000_000:
                    raise ValueError('Максимальный размер: 32 Мп')
                if category in {'frames', 'costumes'} and img.mode not in {'RGBA', 'LA'}:
                    raise ValueError('Для рамки или костюма нужен PNG с прозрачностью')
                img.verify()
            file.seek(0)
            if suffix not in {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}:
                raise ValueError('Неподдерживаемый формат')
        relative = f'{ASSET_CATEGORIES[category]}/{uuid4().hex}_{name}'
        file.save(root / relative)
        return jsonify(path=relative)

    @app.post('/api/render')
    def preview():
        output = io.BytesIO()
        render(request.get_json()).save(output, 'PNG')
        output.seek(0)
        return send_file(output, mimetype='image/png')

    @app.post('/api/export/<fmt>')
    def export(fmt):
        formats = {'png': 'PNG', 'jpeg': 'JPEG', 'tiff': 'TIFF'}
        if fmt not in formats:
            raise ValueError('Неподдерживаемый формат')
        result = render(request.get_json())
        if fmt == 'jpeg':
            white = Image.new('RGB', result.size, 'white')
            white.paste(result, mask=result.getchannel('A'))
            result = white
        output = io.BytesIO()
        result.save(output, formats[fmt], **({'quality': 95} if fmt == 'jpeg' else {}))
        output.seek(0)
        return send_file(output, mimetype=f'image/{fmt}', as_attachment=True, download_name=f'retouch.{fmt}')

    @app.post('/api/transform')
    def transform():
        state = request.get_json()
        result = image(state['path'])
        result = apply_photo_edits(result, state.get('photoEdits', {}).get(state['path'], []))
        action = state['action']
        repair_coverage = None
        if action == 'left': result = result.rotate(90, expand=True)
        elif action == 'right': result = result.rotate(-90, expand=True)
        elif action == 'horizontal': result = ImageOps.mirror(result)
        elif action == 'vertical': result = ImageOps.flip(result)
        elif action == 'redraw':
            from photo_retouch.processing.generative import redraw_photo
            result = redraw_photo(result)
        elif action == 'restore_old':
            from photo_retouch.processing.restoration import restore_old_photo
            result, repair_coverage = restore_old_photo(result, state.get('strength', 50), state.get('repairMarks', {}).get(state['path'], []))
        elif action == 'grayscale':
            alpha = result.getchannel('A')
            result = ImageOps.grayscale(result).convert('RGBA')
            result.putalpha(alpha)
        elif action == 'remove_background':
            from rembg import remove
            original_alpha = result.getchannel('A')
            result = remove(result, session=background_session()).convert('RGBA')
            from PIL import ImageChops
            result.putalpha(ImageChops.multiply(result.getchannel('A'), original_alpha))
        elif action == 'crop':
            box = [int(v) for v in state['box']]
            if len(box) != 4 or not (0 <= box[0] < box[2] <= result.width and 0 <= box[1] < box[3] <= result.height):
                raise ValueError('Неверная область обрезки')
            result = result.crop(box)
        elif action == 'upscale':
            if result.width * result.height > 8_000_000:
                raise ValueError('Для увеличения в 2 раза исходник должен быть не больше 8 Мп')
            result = result.resize((result.width * 2, result.height * 2), Image.Resampling.LANCZOS)
        else: raise ValueError('Неизвестная операция')
        relative = f'02_RestoredPhoto/{uuid4().hex}.png'
        result.save(root / relative)
        return jsonify(path=relative, width=result.width, height=result.height, repairedPercent=repair_coverage)

    @app.post('/api/costume')
    def fit_costume():
        import shutil
        import cv2
        import numpy as np

        source = image(request.get_json()['path'])
        template = Path(app.static_folder) / 'suit.png'
        from photo_retouch.processing.costume import detect_shoulders, warp_suit
        shoulders = detect_shoulders(source)
        if shoulders is not None:
            with Image.open(template) as suit:
                fitted = warp_suit(suit, source.size, shoulders)
            relative = f'06_Costumes/fitted-{uuid4().hex}.png'
            fitted.save(root / relative)
            return jsonify(
                path=relative,
                transform={'position': {'x': source.width / 2, 'y': source.height / 2}, 'scale': 1, 'rotation': 0},
                faceDetected=False, fitMethod='shoulders',
            )
        destination = root / '06_Costumes' / 'formal-suit.png'
        if not destination.exists():
            shutil.copyfile(template, destination)
        gray = cv2.cvtColor(np.array(source), cv2.COLOR_RGBA2GRAY)
        factor = min(1.0, 1000 / max(source.size))
        small = cv2.resize(gray, None, fx=factor, fy=factor)
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = detector.detectMultiScale(small, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
        detected = len(faces) > 0
        if detected:
            x, y, w, h = [float(v) / factor for v in max(faces, key=lambda f: f[2] * f[3])]
            center_x = x + w / 2
            neck_y = y + h * 1.12
            width = w * 3.4
        else:
            center_x = source.width / 2
            neck_y = source.height * .46
            width = source.width * .95
        with Image.open(template) as suit:
            scale = width / suit.width
            height = suit.height * scale
        return jsonify(
            path='06_Costumes/formal-suit.png',
            transform={'position': {'x': center_x, 'y': neck_y + height * .30}, 'scale': scale, 'rotation': 0},
            faceDetected=detected,
            fitMethod='face' if detected else 'manual',
        )

    @app.get('/api/project')
    def load_project():
        path = root / 'web-project.proj'
        return jsonify(json.loads(path.read_text('utf-8')) if path.exists() else Project().to_dict())

    @app.post('/api/project')
    def save_project():
        state = request.get_json()
        render(state)  # Validate referenced resources before saving.
        temporary = root / f'{uuid4().hex}.tmp'
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(root / 'web-project.proj')
        return jsonify(saved=True)

    return app
