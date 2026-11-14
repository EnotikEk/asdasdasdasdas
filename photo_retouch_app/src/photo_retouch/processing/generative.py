"""Generative reconstruction of a complete photo through OpenAI Images Edits."""
import base64
import io
import math
import os
import logging
import re
import requests
from PIL import Image
from werkzeug.exceptions import BadGateway, ServiceUnavailable


def redraw_photo(source):
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ServiceUnavailable('Для полной перерисовки настройте OPENAI_API_KEY в файле .env и перезапустите контейнер.')
    ratio = max(1/3, min(3, source.width / source.height))
    width = round(math.sqrt(1_048_576 * ratio) / 16) * 16
    height = round(width / ratio / 16) * 16
    buffer = io.BytesIO()
    reference = source.copy()
    reference.thumbnail((2048, 2048))
    reference.save(buffer, 'PNG')
    prompt = (
        'Completely reconstruct and redraw this damaged archival photograph as a clean, '
        'photorealistic restored photograph. Rebuild the entire image, not only scratches. '
        'Remove all cracks, fold lines, tears, stains, paper texture and scanning damage. '
        'Reconstruct missing image details plausibly and naturally. Preserve the exact identity, '
        'facial proportions, age, expression, gaze, hairstyle, pose, clothing, composition and '
        'background of every depicted person as faithfully as possible. Do not beautify, '
        'rejuvenate, change clothing or invent accessories. Preserve original monochrome or '
        'sepia treatment; do not colorize a monochrome photograph. Restore natural detail '
        'throughout the image without waxy skin, excessive sharpening, text or watermarks. '
        'Return one fully restored photograph with the same framing and aspect ratio.'
    )
    try:
        response = requests.post(
            'https://api.openai.com/v1/images/edits',
            headers={'Authorization': f'Bearer {key}'},
            data={'model': os.environ.get('OPENAI_IMAGE_MODEL', 'gpt-image-2'), 'prompt': prompt,
                  'quality': 'high', 'size': f'{width}x{height}', 'n': '1'},
            files={'image': ('reference.png', buffer.getvalue(), 'image/png')},
            timeout=(15, 480),
        )
    except requests.RequestException:
        raise BadGateway('Сервис перерисовки недоступен или не ответил вовремя. Проверьте соединение.') from None
    if not response.ok:
        try:
            error = response.json().get('error', {})
            code = error.get('code') or error.get('type') or ''
            code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_\-]{1,80}', code) else ''
        except (ValueError, AttributeError, TypeError):
            code = ''
        logging.getLogger(__name__).warning('OpenAI image edit rejected: status=%s code=%s', response.status_code, code or 'unknown')
        quota_messages = {
            'credit_balance_exhausted': 'На балансе API OpenAI закончились средства. Пополните API Billing: https://platform.openai.com/settings/organization/billing/overview',
            'insufficient_quota': 'OpenAI отклонил запрос из-за квоты API: проверьте баланс и лимиты организации/проекта. https://platform.openai.com/settings/organization/billing/overview',
            'billing_hard_limit_reached': 'Достигнут лимит расходов API OpenAI. Проверьте настройки Billing и Limits.',
            'organization_usage_limit_exceeded': 'Достигнута квота использования организации OpenAI. Проверьте Limits и запросите повышение лимита.',
            'organization_spend_limit_exceeded': 'Достигнут лимит расходов организации OpenAI. Проверьте лимит расходов в Billing.',
            'project_spend_limit_exceeded': 'Достигнут лимит расходов проекта OpenAI. Проверьте лимит проекта, которому принадлежит API-ключ.',
            'rate_limit_exceeded': 'Слишком много запросов к модели OpenAI. Подождите и повторите запрос. Проверьте лимиты модели в https://platform.openai.com/settings/organization/limits',
            'slow_down': 'OpenAI просит снизить частоту запросов. Подождите перед повторным запуском.',
        }
        if code in quota_messages:
            raise BadGateway(f'{quota_messages[code]} Код: {code}')
        messages = {
            401: 'OpenAI отклонил API-ключ. Проверьте OPENAI_API_KEY.',
            403: 'Нет доступа к модели изображений OpenAI. Проверьте доступ проекта и регион.',
            429: 'OpenAI вернул HTTP 429 без уточнения причины. Проверьте API Billing и Limits; повторите запрос позже.',
            400: 'OpenAI отклонил запрос. Проверьте доступность выбранной модели и формат фотографии.',
        }
        raise BadGateway(messages.get(response.status_code, 'Ошибка сервиса OpenAI. Попробуйте позже.'))
    try:
        raw = base64.b64decode(response.json()['data'][0]['b64_json'], validate=True)
        with Image.open(io.BytesIO(raw)) as output:
            output.load()
            restored = output.convert('RGBA')
        if restored.size != source.size:
            restored = restored.resize(source.size, Image.Resampling.LANCZOS)
        return restored
    except (KeyError, IndexError, ValueError, OSError):
        raise BadGateway('OpenAI вернул некорректное изображение.') from None
