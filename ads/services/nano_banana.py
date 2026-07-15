"""
Nano Banana image generation service using Google's Interactions API.
Nano Banana models (gemini-3.1-flash-image, gemini-3-pro-image, gemini-2.5-flash-image)
use the Interactions API at /v1beta/interactions, NOT the predictLongRunning endpoint.
"""
import os
import base64
import time
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers
from ..models import log_api_usage
from .google_models import get_credit_cost


NANO_BANANA_API_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
NANO_BANANA_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

# Map aspect ratios
ASPECT_RATIO_MAP = {
    '1:1': '1:1',
    '4:3': '4:3',
    '3:4': '3:4',
    '16:9': '16:9',
    '9:16': '9:16',
    '3:2': '3:2',
    '2:3': '2:3',
    '1:4': '1:4',
    '4:1': '4:1',
    '1:8': '1:8',
    '8:1': '8:1',
}

# Map aspect ratios to image sizes
IMAGE_SIZE_MAP = {
    '1:1': '2K',
    '16:9': '2K',
    '9:16': '2K',
    '3:2': '2K',
    '2:3': '2K',
    '4:3': '2K',
    '3:4': '2K',
    '1:4': '1K',
    '4:1': '1K',
    '1:8': '1K',
    '8:1': '1K',
}


def _transient_retry(url, headers, body, timeout=180, max_attempts=3):
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


def generate_nano_banana_image(prompt, aspect_ratio='1:1', model_name=None, api_key=None, input_image=None):
    model = model_name or 'gemini-3.1-flash-image'
    url = f'{NANO_BANANA_BASE_URL}/interactions'

    headers = {
        'x-goog-api-key': api_key or NANO_BANANA_API_KEY,
        'Content-Type': 'application/json',
    }

    # Map aspect ratio
    ar = ASPECT_RATIO_MAP.get(aspect_ratio, '1:1')
    image_size = IMAGE_SIZE_MAP.get(ar, '2K')

    input_parts = [{'type': 'text', 'text': prompt}]
    if input_image:
        mime, data = _parse_data_url(input_image)
        input_parts.append({'type': 'image', 'image': {'mime_type': mime, 'data': data}})

    body = {
        'model': model,
        'input': input_parts,
        'response_format': {
            'type': 'image',
            'mime_type': 'image/jpeg',
            'aspect_ratio': ar,
            'image_size': image_size,
        },
    }

    # Retry TRANSIENT errors only (429, 5xx) — these don't cost
    resp = _transient_retry(url, headers, body, timeout=180)
    resp_headers = dict(resp.headers)
    # Log EVERY nano-banana image generation API call (paid POST)
    log_api_usage(f'nb_gen:{model}', success=resp.status_code == 200, response_headers=resp_headers, credit_cost=get_credit_cost(model) or 0)
    if resp.status_code == 429:
        update_ratelimit_from_headers(resp_headers)
        mark_quota_exhausted(resp.text)
        raise QuotaExceededError(resp.text, response_headers=resp_headers)
    if resp.status_code != 200:
        raise Exception(f'Nano Banana API error {resp.status_code}: {resp.text}')

    data = resp.json()

    # Get output image - it can be in different places depending on response structure
    output_image = None
    
    # Check output_image property
    if 'output_image' in data and data['output_image']:
        output_image = data['output_image']
    
    # Check steps for image output
    if not output_image and 'steps' in data:
        for step in data.get('steps', []):
            if 'image' in step:
                output_image = step['image']
                break
    
    if not output_image:
        # Google billed us (200) but returned no image
        log_api_usage(f'nb_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
        raise Exception(f'No image in response: {list(data.keys())}')

    # Extract base64 data
    image_data = None
    if isinstance(output_image, dict):
        image_data = output_image.get('data', '')
    
    if not image_data:
        # Google billed us (200) but returned empty image data
        log_api_usage(f'nb_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
        raise Exception('No image data in output')

    raw = base64.b64decode(image_data)
    return ContentFile(raw, name=_nb_filename(prompt, model)), resp_headers


def _nb_filename(prompt, model):
    """Generate a filename for the generated image."""
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    model_short = model.replace('gemini-', '').replace('-', '_')
    return f'nano_banana_{model_short}_{safe}_{int(time.time())}.jpg'


def _parse_data_url(data_url):
    """Parse 'data:image/png;base64,AAAA' → ('image/png', 'AAAA')."""
    if data_url.startswith('data:'):
        header, b64 = data_url.split(',', 1)
        mime = header.split(';')[0].replace('data:', '')
        return mime, b64
    return 'image/png', data_url
