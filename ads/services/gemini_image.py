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

GEMINI_API_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'


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

    resp = requests.post(url, headers=headers, json=body, timeout=300)
    resp_headers = dict(resp.headers)
    if resp.status_code == 429:
        update_ratelimit_from_headers(resp_headers)
        mark_quota_exhausted(resp.text)
        raise QuotaExceededError(resp.text, response_headers=resp_headers)
    if resp.status_code != 200:
        raise Exception(f'Gemini API error {resp.status_code}: {resp.text}')

    data = resp.json()

    candidates = data.get('candidates', [])
    if not candidates:
        raise Exception(f'No candidates in response: {data}')

    parts = candidates[0].get('content', {}).get('parts', [])
    image_data = None
    for part in parts:
        inline_data = part.get('inlineData', {})
        if inline_data.get('mimeType', '').startswith('image/'):
            image_data = inline_data.get('data', '')
            break

    if not image_data:
        # Log the full response for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Gemini image response missing image data. Parts: {parts}')
        raise Exception(
            f'No image data in Gemini response — the model returned text instead of an image. '
            f'Try a more descriptive prompt. Response parts: {[list(p.keys()) for p in parts]}'
        )

    raw = base64.b64decode(image_data)
    return ContentFile(raw, name=_gemini_filename(prompt, model)), resp_headers


def _gemini_filename(prompt, model):
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    model_short = model.replace('gemini-', '').replace('-', '_')
    return f'gemini_{model_short}_{safe}_{int(time.time())}.jpg'
