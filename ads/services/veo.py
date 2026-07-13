import os
import json
import re
import time
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers
from ..models import log_api_usage
from .google_models import get_credit_cost


GEMINI_STUDIO_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
VEO_BASE_URL = os.environ.get('VEO_BASE_URL') or 'https://generativelanguage.googleapis.com/v1beta'


VEO_SUPPORTED_ASPECT_RATIOS = {'16:9', '9:16', '4:3', '3:4'}


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
    """Parse a data URL and return (raw_base64, mime_type)."""
    match = re.match(r'^data:([^;]+);base64,(.+)$', data_url, re.DOTALL)
    if match:
        return match.group(2), match.group(1)
    return data_url, 'image/png'


def _start_generation(prompt, duration_seconds, aspect_ratio, effective_key, model, poll_interval=5, input_image_base64=None, input_image_mime='image/png'):
    url = f'{VEO_BASE_URL}/models/{model}:predictLongRunning'
    headers = {
        'X-Goog-Api-Key': effective_key,
        'Content-Type': 'application/json',
    }

    instance = {'prompt': prompt}
    if input_image_base64:
        raw_base64, detected_mime = _parse_data_url(input_image_base64)
        instance['image'] = {
            'bytesBase64Encoded': raw_base64,
            'mimeType': detected_mime,
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


def generate_video_from_text(prompt, duration_seconds=8, aspect_ratio='16:9', poll_interval=5, model_name=None, api_key=None, target_duration_seconds=None, input_image_base64=None, input_image_mime='image/png'):
    model = model_name or 'veo-3.1-generate-preview'
    effective_key = api_key or GEMINI_STUDIO_KEY

    if aspect_ratio not in VEO_SUPPORTED_ASPECT_RATIOS:
        aspect_ratio = '16:9'

    target = target_duration_seconds or duration_seconds
    # Veo generates a single clip up to 8 seconds max. No splitting needed.
    clip_duration = min(8, target) if target else 8
    uri, resp_headers = _start_generation(prompt, clip_duration, aspect_ratio, effective_key, model, poll_interval, input_image_base64, input_image_mime)

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
