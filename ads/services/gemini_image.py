"""
Image generation via Gemini API's generateContent endpoint.
Uses image-capable models like gemini-2.5-flash-image, gemini-3.1-flash-image, etc.
All image models are paid (consume credits) — no free tier for image generation.
"""
import os
import time
import base64
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers
from ..models import log_api_usage
from .google_models import get_credit_cost

GEMINI_API_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'


def _transient_retry(url, headers, body, timeout=300, max_attempts=3):
    """Retry POST on transient failures (429, 5xx, network issues) that DON'T bill."""
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


def generate_gemini_image(prompt, aspect_ratio='1:1', model_name=None, api_key=None):
    model = model_name or 'gemini-3.1-flash-image'
    url = f'{GEMINI_BASE_URL}/models/{model}:generateContent'

    effective_key = api_key or GEMINI_API_KEY
    headers = {
        'x-goog-api-key': effective_key,
        'Content-Type': 'application/json',
    }

    body = {
        'contents': [{
            'parts': [{'text': prompt}],
        }],
    }

    # Retry TRANSIENT errors only (429, 5xx) — these don't cost
    resp = _transient_retry(url, headers, body, timeout=300)
    resp_headers = dict(resp.headers)
    # Log EVERY Gemini image generation API call (paid POST)
    log_api_usage(f'gemini_gen:{model}', success=resp.status_code == 200, response_headers=resp_headers, credit_cost=get_credit_cost(model) or 0)
    if resp.status_code == 429:
        update_ratelimit_from_headers(resp_headers)
        mark_quota_exhausted(resp.text)
        raise QuotaExceededError(resp.text, response_headers=resp_headers)
    if resp.status_code != 200:
        raise Exception(f'Gemini API error {resp.status_code}: {resp.text}')

    data = resp.json()

    candidates = data.get('candidates', [])
    if not candidates:
        # Google billed us (200) but returned no image
        log_api_usage(f'gemini_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
        raise Exception(f'No candidates in response: {data}')

    parts = candidates[0].get('content', {}).get('parts', [])
    image_data = None
    for part in parts:
        inline_data = part.get('inlineData', {})
        if inline_data.get('mimeType', '').startswith('image/'):
            image_data = inline_data.get('data', '')
            break

    if not image_data:
        # Google billed us (200) but returned text instead of image (content block)
        log_api_usage(f'gemini_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Gemini image response missing image data. Parts: {parts}')
        raise Exception(
            f'No image data in Gemini response — the model returned text instead of an image. '
            f'This likely means a safety filter blocked the image. Try a different prompt.'
        )

    raw = base64.b64decode(image_data)
    return ContentFile(raw, name=_gemini_filename(prompt, model)), resp_headers


def _gemini_filename(prompt, model):
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    model_short = model.replace('gemini-', '').replace('-', '_')
    return f'gemini_{model_short}_{safe}_{int(time.time())}.jpg'
