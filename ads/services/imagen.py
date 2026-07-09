import os
import time
import base64
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers
from ..models import log_api_usage
from .google_models import get_credit_cost


IMAGEN_API_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
IMAGEN_BASE_URL = os.environ.get('VEO_BASE_URL') or 'https://generativelanguage.googleapis.com/v1beta'


def _transient_retry(url, headers, body, timeout=60, max_attempts=3):
    """Retry POST on transient failures (429, 5xx, network issues) that DON'T bill.
    Does NOT retry on 200+processing failures (those already billed)."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                time.sleep(2 ** attempt * 2)
                continue
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < max_attempts:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise last_exc or Exception(f'Request failed after {max_attempts} attempts')


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

    # Retry TRANSIENT errors only (429, 5xx) — these don't cost
    resp = _transient_retry(url, headers, body, timeout=60)
    resp_headers = dict(resp.headers)
    # Log EVERY image generation API call (paid POST)
    log_api_usage(f'imagen_gen:{model}', success=resp.status_code == 200, response_headers=resp_headers, credit_cost=get_credit_cost(model) or 0)
    if resp.status_code == 429:
        update_ratelimit_from_headers(resp_headers)
        mark_quota_exhausted(resp.text)
        raise QuotaExceededError(resp.text, response_headers=resp_headers)
    if resp.status_code != 200:
        raise Exception(f'Imagen API error {resp.status_code}: {resp.text}')

    data = resp.json()
    predictions = data.get('predictions', [])
    if not predictions:
        # Google billed us (200) but returned no image
        log_api_usage(f'imagen_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
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

    # Google billed us (200) but format was unexpected
    log_api_usage(f'imagen_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
    raise Exception(f'Unexpected prediction format: {list(prediction.keys())}')


def _img_filename(prompt, mime_type):
    ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    return f'imagen_{safe}_{int(time.time())}.{ext}'
