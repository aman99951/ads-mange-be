import os
import base64
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers


IMAGEN_API_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
IMAGEN_BASE_URL = os.environ.get('VEO_BASE_URL') or 'https://generativelanguage.googleapis.com/v1beta'


def generate_image_from_text(prompt, aspect_ratio='1:1', sample_count=1, poll_interval=3, model_name=None, api_key=None):
    model = model_name or 'imagen-4.0-generate-001'
    url = f'{IMAGEN_BASE_URL}/models/{model}:predict'
    effective_key = api_key or IMAGEN_API_KEY

    headers = {
        'X-Goog-Api-Key': effective_key,
        'Content-Type': 'application/json',
    }

    body = {
        'instances': [{
            'prompt': prompt,
        }],
        'parameters': {
            'aspectRatio': aspect_ratio,
            'sampleCount': sample_count,
        },
    }

    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp_headers = dict(resp.headers)
    if resp.status_code == 429:
        update_ratelimit_from_headers(resp_headers)
        mark_quota_exhausted(resp.text)
        raise QuotaExceededError(resp.text, response_headers=resp_headers)
    if resp.status_code != 200:
        raise Exception(f'Imagen API error {resp.status_code}: {resp.text}')

    data = resp.json()
    predictions = data.get('predictions', [])
    if not predictions:
        raise Exception('No image generated: empty predictions')

    prediction = predictions[0]

    if 'image' in prediction:
        b64 = prediction['image']
        if isinstance(b64, dict):
            b64 = b64.get('bytesImage', '')
        raw = base64.b64decode(b64)
        mime_type = prediction.get('mimeType', 'image/png')
        return ContentFile(raw, name=_img_filename(prompt, mime_type)), resp_headers

    if 'bytesBase64Encoded' in prediction:
        raw = base64.b64decode(prediction['bytesBase64Encoded'])
        mime_type = prediction.get('mimeType', 'image/png')
        return ContentFile(raw, name=_img_filename(prompt, mime_type)), resp_headers

    encoded = prediction.get('encodedImage', '')
    if encoded:
        raw = base64.b64decode(encoded)
        return ContentFile(raw, name=_img_filename(prompt, 'image/png')), resp_headers

    raise Exception(f'Unexpected prediction format: {list(prediction.keys())}')


def _img_filename(prompt, mime_type):
    ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    return f'imagen_{safe}_{int(time.time())}.{ext}'
