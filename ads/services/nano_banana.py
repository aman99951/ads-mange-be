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


def generate_nano_banana_image(prompt, aspect_ratio='1:1', model_name=None, api_key=None):
    model = model_name or 'gemini-3.1-flash-image'
    url = f'{NANO_BANANA_BASE_URL}/interactions'

    headers = {
        'x-goog-api-key': api_key or NANO_BANANA_API_KEY,
        'Content-Type': 'application/json',
    }

    # Map aspect ratio
    ar = ASPECT_RATIO_MAP.get(aspect_ratio, '1:1')
    image_size = IMAGE_SIZE_MAP.get(ar, '2K')

    body = {
        'model': model,
        'input': [
            {'type': 'text', 'text': prompt},
        ],
        'response_format': {
            'type': 'image',
            'mime_type': 'image/jpeg',
            'aspect_ratio': ar,
            'image_size': image_size,
        },
    }

    resp = requests.post(url, headers=headers, json=body, timeout=180)
    resp_headers = dict(resp.headers)
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
        raise Exception(f'No image in response: {list(data.keys())}')

    # Extract base64 data
    image_data = None
    if isinstance(output_image, dict):
        image_data = output_image.get('data', '')
    
    if not image_data:
        raise Exception('No image data in output')

    raw = base64.b64decode(image_data)
    return ContentFile(raw, name=_nb_filename(prompt, model)), resp_headers


def _nb_filename(prompt, model):
    """Generate a filename for the generated image."""
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    model_short = model.replace('gemini-', '').replace('-', '_')
    return f'nano_banana_{model_short}_{safe}_{int(time.time())}.jpg'
