import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from photo_retouch.web import create_app
from photo_retouch.core.models import Project


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = create_app(self.root).test_client()
        buffer = io.BytesIO()
        Image.new('RGBA', (40, 20), (120, 60, 30, 128)).save(buffer, 'PNG')
        self.original = buffer.getvalue()
        response = self.client.post('/api/upload/initial_photo', data={'file': (io.BytesIO(self.original), 'test.png')})
        self.assertEqual(response.status_code, 200)
        self.path = response.json['path']
        self.state = Project(initial_photo=self.path).to_dict()

    def tearDown(self):
        self.temp.cleanup()

    def test_page_and_assets(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/health').json, {'status': 'ok'})
        self.assertIn(self.path, self.client.get('/api/assets').json['initial_photo'])

    def test_adjustments_and_export(self):
        first = self.client.post('/api/render', json=self.state)
        self.assertEqual(first.status_code, 200)
        self.state['adjustments']['brightness'] = 50
        second = self.client.post('/api/render', json=self.state)
        self.assertNotEqual(first.data, second.data)
        for fmt in ['png', 'jpeg', 'tiff']:
            response = self.client.post('/api/export/' + fmt, json=self.state)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(Image.open(io.BytesIO(response.data)).size, (40, 20))

    def test_transform_preserves_original_and_crop(self):
        result = self.client.post('/api/transform', json={'path': self.path, 'action': 'right'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual((result.json['width'], result.json['height']), (20, 40))
        self.assertEqual((self.root / self.path).read_bytes(), self.original)
        cropped = self.client.post('/api/transform', json={'path': self.path, 'action': 'crop', 'box': [0, 0, 10, 10]})
        self.assertEqual(cropped.json['width'], 10)

    def test_project_round_trip(self):
        self.state['costumeOpacity'] = .4
        self.state['layerOrder'] = ['photo', 'background', 'costume', 'frame', 'text']
        self.assertEqual(self.client.post('/api/project', json=self.state).status_code, 200)
        self.assertEqual(self.client.get('/api/project').json, self.state)

    def test_invalid_paths_uploads_and_order(self):
        self.state['initialPhoto'] = '../outside.png'
        self.assertEqual(self.client.post('/api/render', json=self.state).status_code, 400)
        response = self.client.post('/api/upload/initial_photo', data={'file': (io.BytesIO(b'bad'), 'bad.png')})
        self.assertEqual(response.status_code, 400)
        self.state['initialPhoto'] = self.path
        self.state['layerOrder'] = ['photo']
        self.assertEqual(self.client.post('/api/render', json=self.state).status_code, 400)

    def test_sharpness_preserves_alpha(self):
        from photo_retouch.processing.engine import ImageProcessor
        from photo_retouch.core.models import Adjustments
        image = Image.new('RGBA', (10, 10), (120, 60, 30, 128))
        result = ImageProcessor.apply_adjustments(image, Adjustments(sharpness=20))
        self.assertEqual(result.getchannel('A').getextrema(), (128, 128))

    def test_font_size_changes_rendered_text(self):
        from photo_retouch.processing.engine import TextRenderer
        from photo_retouch.core.models import TextOverlay, TextStyle, Point
        sizes = []
        for size in [20, 80]:
            overlay = TextOverlay(content='Привет', position=Point(300, 180), style=TextStyle(font_size=size, stroke_enabled=False))
            rendered = TextRenderer.render_text(overlay, (600, 400))
            box = rendered.getbbox()
            sizes.append((box[2] - box[0], box[3] - box[1]))
        self.assertGreater(sizes[1][0], sizes[0][0] * 2)
        self.assertGreater(sizes[1][1], sizes[0][1] * 2)

    def test_grayscale_preserves_alpha_and_source(self):
        result = self.client.post('/api/transform', json={'path': self.path, 'action': 'grayscale'})
        self.assertEqual(result.status_code, 200)
        with Image.open(self.root / result.json['path']) as image:
            r, g, b, alpha = image.getpixel((0, 0))
            self.assertEqual(r, g)
            self.assertEqual(g, b)
            self.assertEqual(alpha, 128)
        self.assertEqual((self.root / self.path).read_bytes(), self.original)

    def test_background_removal_real_model(self):
        from PIL import ImageDraw
        image = Image.new('RGB', (256, 256), 'white')
        draw = ImageDraw.Draw(image)
        draw.ellipse((70, 30, 185, 230), fill='red')
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        result = self.client.post('/api/upload/initial_photo', data={'file': (io.BytesIO(buffer.getvalue()), 'object.png')})
        response = self.client.post('/api/transform', json={'path': result.json['path'], 'action': 'remove_background'})
        self.assertEqual(response.status_code, 200, response.json)
        with Image.open(self.root / response.json['path']) as cutout:
            self.assertEqual(cutout.mode, 'RGBA')
            self.assertLess(cutout.getpixel((0, 0))[3], 30)
            self.assertGreater(cutout.getpixel((128, 128))[3], 150)

    def test_suit_fallback_and_render(self):
        response = self.client.post('/api/costume', json={'path': self.path})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(response.json['faceDetected'])
        self.state['costume'] = response.json['path']
        self.state['costumeTransform'] = response.json['transform']
        self.assertTrue((self.root / response.json['path']).exists())
        rendered = self.client.post('/api/render', json=self.state)
        self.assertEqual(rendered.status_code, 200)
        self.assertEqual((self.root / self.path).read_bytes(), self.original)

    def test_suit_uses_largest_face(self):
        from unittest.mock import patch
        import numpy as np
        with patch('cv2.CascadeClassifier') as detector:
            detector.return_value.detectMultiScale.return_value = np.array([[2, 1, 4, 4], [10, 2, 8, 8]])
            response = self.client.post('/api/costume', json={'path': self.path})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['faceDetected'])
        self.assertEqual(response.json['transform']['position']['x'], 14)
        with Image.open(self.root / response.json['path']) as suit:
            self.assertEqual(suit.mode, 'RGBA')
            self.assertEqual(suit.getchannel('A').getextrema(), (0, 255))

    def test_suit_fits_shoulder_width_and_tilt(self):
        from unittest.mock import patch
        import numpy as np
        from photo_retouch.processing.costume import warp_suit
        template = Image.new('RGBA', (100, 100), (200, 10, 10, 255))
        narrow = warp_suit(template, (400, 400), (np.array([150, 100]), np.array([250, 100])))
        wide = warp_suit(template, (400, 400), (np.array([100, 100]), np.array([300, 100])))
        self.assertGreater(wide.getbbox()[2]-wide.getbbox()[0], narrow.getbbox()[2]-narrow.getbbox()[0])
        with patch('photo_retouch.processing.costume.detect_shoulders', return_value=(np.array([10, 5]), np.array([30, 8]))):
            response = self.client.post('/api/costume', json={'path': self.path})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['fitMethod'], 'shoulders')
        self.assertEqual(response.json['transform']['scale'], 1)
        with Image.open(self.root / response.json['path']) as suit:
            self.assertEqual(suit.size, (40, 20))
        self.state['costume'] = response.json['path']
        self.state['costumeTransform'] = response.json['transform']
        self.assertEqual(self.client.post('/api/render', json=self.state).status_code, 200)

    def test_eraser_restore_export_and_project(self):
        path = self.path
        self.state['photoEdits'] = {path: [{'mode': 'erase', 'size': .5, 'points': [[.5, .5]]}]}
        erased = self.client.post('/api/render', json=self.state)
        self.assertEqual(erased.status_code, 200)
        with Image.open(io.BytesIO(erased.data)) as image:
            self.assertEqual(image.getpixel((20, 10))[3], 0)
            self.assertEqual(image.getpixel((0, 0))[3], 128)
        self.state['photoEdits'][path].append({'mode': 'restore', 'size': .2, 'points': [[.5, .5]]})
        restored = self.client.post('/api/export/png', json=self.state)
        with Image.open(io.BytesIO(restored.data)) as image:
            self.assertEqual(image.getpixel((20, 10))[3], 128)
            self.assertEqual(image.getpixel((24, 10))[3], 0)
        self.assertEqual(self.client.post('/api/project', json=self.state).status_code, 200)
        self.assertEqual(self.client.get('/api/project').json['photoEdits'], self.state['photoEdits'])
        self.assertEqual((self.root / path).read_bytes(), self.original)

    def test_eraser_is_kept_when_transforming(self):
        edits = {self.path: [{'mode': 'erase', 'size': .5, 'points': [[.5, .5]]}]}
        response = self.client.post('/api/transform', json={'path': self.path, 'action': 'grayscale', 'photoEdits': edits})
        self.assertEqual(response.status_code, 200)
        with Image.open(self.root / response.json['path']) as image:
            self.assertEqual(image.getpixel((20, 10))[3], 0)

    def test_eraser_invalid_stroke(self):
        self.state['photoEdits'] = {self.path: [{'mode': 'erase', 'size': .5, 'points': [[2, .5]]}]}
        self.assertEqual(self.client.post('/api/render', json=self.state).status_code, 400)

    def test_old_photo_repairs_synthetic_scratch(self):
        import numpy as np
        from PIL import ImageDraw
        from photo_retouch.processing.restoration import restore_old_photo
        source = Image.new('RGBA', (200, 200), (95, 95, 95, 128))
        ImageDraw.Draw(source).line((10, 100, 190, 100), fill=(240, 240, 240, 128), width=2)
        repaired, coverage = restore_old_photo(source)
        self.assertGreater(coverage, 0)
        self.assertLess(abs(repaired.getpixel((100, 100))[0]-95), 20)
        self.assertEqual(repaired.getchannel('A').getextrema(), (128, 128))
        marks = [{'mode': 'erase', 'size': .05, 'points': [[.05, .5], [.95, .5]]}]
        manual, coverage = restore_old_photo(source, marks=marks)
        self.assertLess(abs(manual.getpixel((100, 100))[0]-95), 20)

    def test_old_photo_endpoint_and_source_preserved(self):
        response = self.client.post('/api/transform', json={'path': self.path, 'action': 'restore_old', 'strength': 50})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIn('repairedPercent', response.json)
        self.assertNotEqual(response.json['path'], self.path)
        self.assertEqual((self.root / self.path).read_bytes(), self.original)
        response = self.client.post('/api/transform', json={'path': self.path, 'action': 'restore_old', 'strength': 999})
        self.assertEqual(response.status_code, 400)

    def test_redraw_requires_key(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            self.assertFalse(self.client.get('/api/ai-status').json['configured'])
            response = self.client.post('/api/transform', json={'path': self.path, 'action': 'redraw'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual((self.root / self.path).read_bytes(), self.original)

    def test_redraw_calls_image_edit_and_saves_full_result(self):
        import base64
        from unittest.mock import patch, Mock
        output = io.BytesIO()
        Image.new('RGB', (100, 100), 'blue').save(output, 'PNG')
        remote = Mock(ok=True)
        remote.json.return_value = {'data': [{'b64_json': base64.b64encode(output.getvalue()).decode()}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('photo_retouch.processing.generative.requests.post', return_value=remote) as post:
            response = self.client.post('/api/transform', json={'path': self.path, 'action': 'redraw'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(post.call_count, 1)
        self.assertIn('image', post.call_args.kwargs['files'])
        self.assertNotIn('mask', post.call_args.kwargs['files'])
        with Image.open(self.root / response.json['path']) as image:
            self.assertEqual(image.size, (40, 20))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual((self.root / self.path).read_bytes(), self.original)

    def test_redraw_remote_error_is_not_retried(self):
        from unittest.mock import patch, Mock
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('photo_retouch.processing.generative.requests.post', return_value=Mock(ok=False, status_code=429)) as post:
            response = self.client.post('/api/transform', json={'path': self.path, 'action': 'redraw'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(post.call_count, 1)

    def test_redraw_distinguishes_quota_from_rate_limit(self):
        from unittest.mock import patch, Mock
        for code, expected in [('insufficient_quota', 'квоты API'), ('credit_balance_exhausted', 'закончились средства'), ('rate_limit_exceeded', 'Слишком много запросов'), ('project_spend_limit_exceeded', 'расходов проекта')]:
            remote = Mock(ok=False, status_code=429)
            remote.json.return_value = {'error': {'code': code, 'type': 'insufficient_quota'}}
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('photo_retouch.processing.generative.requests.post', return_value=remote):
                response = self.client.post('/api/transform', json={'path': self.path, 'action': 'redraw'})
            self.assertEqual(response.status_code, 502)
            self.assertIn(expected, response.json['error'])
            self.assertIn(code, response.json['error'])
