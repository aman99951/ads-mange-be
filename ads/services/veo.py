import os
import json
import re
import time
import base64
import io
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers
from ..models import log_api_usage
from .google_models import get_credit_cost


GEMINI_STUDIO_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
VEO_BASE_URL = os.environ.get('VEO_BASE_URL') or 'https://generativelanguage.googleapis.com/v1beta'


VEO_SUPPORTED_ASPECT_RATIOS = {'16:9', '9:16'}
VEO_SUPPORTED_IMAGE_MIMES = {'image/png', 'image/jpeg', 'image/webp'}
VEO_MAX_IMAGE_BASE64_CHARS = 15 * 1024 * 1024   # ~15MB base64 ≈ ~11MB decoded
VEO_MIN_IMAGE_DIMENSION = 64                     # minimum width or height in px
VEO_MAX_IMAGE_DIMENSION = 4096                   # maximum width or height in px


def _poll_operation(operation_name, effective_key, model, poll_interval=5):
    while True:
        op_resp = requests.get(
            f'{VEO_BASE_URL}/{operation_name}',
            headers={'X-Goog-Api-Key': effective_key},
            timeout=30,
        )
        # Log every poll request (GET, not billable but tracked for visibility)
        log_api_usage(f'veo_poll:{operation_name.split("/")[-1][:20]}', success=op_resp.status_code == 200, credit_cost=0)

        if op_resp.status_code != 200:
            raise Exception(f'Veo operation poll error {op_resp.status_code}: {op_resp.text}')

        op_data = op_resp.json()

        if op_data.get('done'):
            if 'error' in op_data:
                err = op_data['error']
                # Google billed us (POST returned 200) but generation failed mid-way
                log_api_usage(f'veo_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
                raise Exception(f'Veo generation failed: {err.get("message", str(err))}')
            return op_data

        time.sleep(poll_interval)


def _transient_retry(url, headers, body, timeout=60, max_attempts=3):
    """Retry POST on transient failures (429, 5xx, network issues) that DON'T bill.
    These errors happen BEFORE Google accepts the request, so no cost.
    Does NOT retry on 200+processing failures (those already billed)."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                wait = 2 ** attempt * 2  # 4s, 8s, 16s
                time.sleep(wait)
                continue
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < max_attempts:
                wait = 2 ** attempt * 2
                time.sleep(wait)
                continue
            raise
    raise last_exc or Exception(f'Request failed after {max_attempts} attempts')


def _parse_data_url(data_url):
    """Parse a data URL and return (raw_base64, mime_type).

    Raises ValueError if the input is not a valid base64 data URL.
    """
    match = re.match(r'^data:([^;]+);base64,(.+)$', data_url, re.DOTALL)
    if match:
        return match.group(2), match.group(1)
    raise ValueError(
        'Invalid input_image: expected a data URL (data:<mime>;base64,...). '
        'Raw URLs or non-base64 data are not accepted.'
    )


def _validate_image(input_image_base64):
    """Strict pre-flight validation of input_image BEFORE any Veo API call.

    Validates:
      1. Data URL format
      2. MIME type is supported by Veo
      3. Base64 payload size
      4. Base64 decodes successfully
      5. Decoded bytes are a real image (opened with Pillow)
      6. Image dimensions within Veo limits

    Returns (raw_base64, mime_type) on success.
    Raises ValueError on ANY failure — never reaches Veo API.
    """
    from PIL import Image

    # 1. Must be a valid data URL
    raw_base64, mime_type = _parse_data_url(input_image_base64)

    # 2. MIME type must be supported
    if mime_type not in VEO_SUPPORTED_IMAGE_MIMES:
        raise ValueError(
            f'Unsupported image type: {mime_type}. '
            f'Supported: {", ".join(sorted(VEO_SUPPORTED_IMAGE_MIMES))}'
        )

    # 3. Base64 size check (before decoding — fast)
    if len(raw_base64) > VEO_MAX_IMAGE_BASE64_CHARS:
        size_mb = len(raw_base64) // (1024 * 1024)
        raise ValueError(
            f'Image too large ({size_mb}MB). Maximum allowed is ~11MB.'
        )

    if len(raw_base64) < 100:
        raise ValueError('Image data is too small or empty.')

    # 4. Decode base64 — catches corrupted/truncated data
    try:
        image_bytes = base64.b64decode(raw_base64, validate=True)
    except Exception:
        raise ValueError(
            'Image data is corrupted (invalid base64). '
            'Please re-upload the image.'
        )

    if len(image_bytes) < 50:
        raise ValueError('Decoded image data is too small — likely not a valid image.')

    # 5. Open with Pillow — verifies it is a real decodable image
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # verifies file integrity (checks headers, not full decode)
    except Exception:
        raise ValueError(
            'The file is not a valid image or is corrupted. '
            'Please upload a PNG, JPEG, or WebP file.'
        )

    # Re-open after verify() (verify() consumes the file handle)
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
    except Exception:
        raise ValueError('Could not read image dimensions — file may be corrupted.')

    # 6. Dimension limits
    if width < VEO_MIN_IMAGE_DIMENSION or height < VEO_MIN_IMAGE_DIMENSION:
        raise ValueError(
            f'Image is too small ({width}x{height}). '
            f'Minimum dimension is {VEO_MIN_IMAGE_DIMENSION}x{VEO_MIN_IMAGE_DIMENSION}.'
        )

    if width > VEO_MAX_IMAGE_DIMENSION or height > VEO_MAX_IMAGE_DIMENSION:
        raise ValueError(
            f'Image is too large ({width}x{height}). '
            f'Maximum dimension is {VEO_MAX_IMAGE_DIMENSION}x{VEO_MAX_IMAGE_DIMENSION}.'
        )

    return raw_base64, mime_type


def _start_generation(prompt, duration_seconds, aspect_ratio, effective_key, model, poll_interval=5, input_image_base64=None, input_image_mime='image/png', last_frame_base64=None, last_frame_mime='image/png'):
    url = f'{VEO_BASE_URL}/models/{model}:predictLongRunning'
    headers = {
        'X-Goog-Api-Key': effective_key,
        'Content-Type': 'application/json',
    }

    instance = {'prompt': prompt}
    if input_image_base64:
        # Strict validation — raises ValueError before ANY Veo API call
        raw_base64, detected_mime = _validate_image(input_image_base64)
        instance['image'] = {
            'bytesBase64Encoded': raw_base64,
            'mimeType': detected_mime,
        }
    if last_frame_base64:
        raw_last, detected_last_mime = _validate_image(last_frame_base64)
        instance['lastFrame'] = {
            'bytesBase64Encoded': raw_last,
            'mimeType': detected_last_mime,
        }

    body = {
        'instances': [instance],
        'parameters': {
            'durationSeconds': duration_seconds,
            'aspectRatio': aspect_ratio,
            'sampleCount': 1,
        },
    }

    # Retry on TRANSIENT errors (429, 5xx) — these don't cost since request was rejected
    # Does NOT retry on accepted requests that fail mid-processing (those already billed)
    resp = _transient_retry(url, headers, body, timeout=60)
    resp_headers = dict(resp.headers)

    # Log EVERY Veo generation request (paid POST call)
    log_api_usage(f'veo_gen:{model}', success=resp.status_code == 200, credit_cost=get_credit_cost(model) or 0)

    if resp.status_code == 429:
        update_ratelimit_from_headers(resp_headers)
        mark_quota_exhausted(resp.text)
        raise QuotaExceededError(resp.text, response_headers=resp_headers)

    if resp.status_code != 200:
        raise Exception(f'Veo API error {resp.status_code}: {resp.text}')

    operation = resp.json()
    operation_name = operation.get('name')
    if not operation_name:
        raise Exception(f'No operation name in response: {operation}')

    op_data = _poll_operation(operation_name, effective_key, model, poll_interval)
    generated_samples = (
        op_data.get('response', {})
        .get('generateVideoResponse', {})
        .get('generatedSamples', [])
    )
    if not generated_samples:
        # Google billed us but returned no video
        log_api_usage(f'veo_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
        raise Exception('No video generated: empty predictions')
    video_info = generated_samples[0].get('video', {})
    video_uri = video_info.get('uri', '')
    if video_uri:
        return video_uri, resp_headers
    # Google billed us but returned unexpected format
    log_api_usage(f'veo_billed_fail:{model}', success=False, credit_cost=get_credit_cost(model) or 0)
    raise Exception(f'Unexpected response format: {list(op_data.get("response", {}).keys())}')


def generate_video_from_text(prompt, duration_seconds=8, aspect_ratio='16:9', poll_interval=5, model_name=None, api_key=None, target_duration_seconds=None, input_image_base64=None, input_image_mime='image/png', last_frame_base64=None, last_frame_mime='image/png'):
    # ── Strict pre-flight validation — ALL checks BEFORE any Veo API call ──

    # Prompt validation
    prompt = (prompt or '').strip()
    if not prompt:
        raise ValueError('Prompt is required and cannot be empty.')
    if len(prompt) > 5000:
        raise ValueError(f'Prompt too long ({len(prompt)} chars). Maximum is 5000 characters.')

    # API key validation
    model = model_name or 'veo-3.1-generate-preview'
    effective_key = api_key or GEMINI_STUDIO_KEY
    if not effective_key:
        raise ValueError('No API key configured. Please set a Google API key.')

    # Aspect ratio validation
    if aspect_ratio not in VEO_SUPPORTED_ASPECT_RATIOS:
        raise ValueError(
            f'Unsupported aspect ratio: {aspect_ratio}. '
            f'Supported: {", ".join(sorted(VEO_SUPPORTED_ASPECT_RATIOS))}'
        )

    # Duration validation
    target = target_duration_seconds or duration_seconds
    clip_duration = min(8, target) if target else 8
    if clip_duration not in (4, 6, 8):
        clip_duration = 8

    # Image validation (if provided) — decoded & verified with Pillow BEFORE any API call
    if input_image_base64:
        _validate_image(input_image_base64)
    if last_frame_base64:
        _validate_image(last_frame_base64)

    # ── All validation passed — safe to call Veo ──
    uri, resp_headers = _start_generation(prompt, clip_duration, aspect_ratio, effective_key, model, poll_interval, input_image_base64, input_image_mime, last_frame_base64, last_frame_mime)

    # Log the video download — if we reach here, output was delivered successfully
    # Note: credit_cost=0 because the cost was already counted in veo_gen above
    log_api_usage(f'veo_output:{model}', success=True, credit_cost=0)
    video_file = _download_from_uri(uri, prompt, effective_key)
    return video_file, resp_headers


def _download_from_gcs(gcs_uri, prompt):
    try:
        from google.cloud import storage
    except ImportError:
        raise Exception(
            'google-cloud-storage not installed. Install it with: pip install google-cloud-storage'
        )
    bucket_name, blob_path = gcs_uri.replace('gs://', '').split('/', 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    content_type = blob.content_type or 'video/mp4'
    raw = blob.download_as_bytes()
    return ContentFile(raw, name=_filename(prompt, content_type))


def _download_from_uri(file_uri, prompt, api_key=None):
    headers = {'X-Goog-Api-Key': api_key or GEMINI_STUDIO_KEY}
    resp = requests.get(file_uri, headers=headers, stream=True, timeout=120)
    if resp.status_code != 200:
        raise Exception(f'Failed to download video from {file_uri}: {resp.status_code}')
    content_type = resp.headers.get('Content-Type', 'video/mp4')
    return ContentFile(resp.content, name=_filename(prompt, content_type))


def _filename(prompt, mime_type):
    ext = mime_type.split('/')[-1] if '/' in mime_type else 'mp4'
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    return f'veo_{safe}_{int(time.time())}.{ext}'
