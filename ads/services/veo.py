import os
import json
import time
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .google_quota import QuotaExceededError, mark_quota_exhausted, update_ratelimit_from_headers


GEMINI_STUDIO_KEY = os.environ.get('GEMINI_STUDIO_KEY') or getattr(settings, 'GEMINI_STUDIO_KEY', '')
VEO_BASE_URL = os.environ.get('VEO_BASE_URL') or 'https://generativelanguage.googleapis.com/v1beta'


VEO_SUPPORTED_ASPECT_RATIOS = {'16:9', '9:16', '4:3', '3:4'}


def _poll_operation(operation_name, effective_key, poll_interval=5):
    while True:
        op_resp = requests.get(
            f'{VEO_BASE_URL}/{operation_name}',
            headers={'X-Goog-Api-Key': effective_key},
            timeout=30,
        )
        if op_resp.status_code != 200:
            raise Exception(f'Veo operation poll error {op_resp.status_code}: {op_resp.text}')

        op_data = op_resp.json()

        if op_data.get('done'):
            if 'error' in op_data:
                err = op_data['error']
                raise Exception(f'Veo generation failed: {err.get("message", str(err))}')
            return op_data

        time.sleep(poll_interval)


def _start_generation(prompt, duration_seconds, aspect_ratio, effective_key, model, previous_video_uri=None, poll_interval=5):
    url = f'{VEO_BASE_URL}/models/{model}:predictLongRunning'
    headers = {
        'X-Goog-Api-Key': effective_key,
        'Content-Type': 'application/json',
    }

    instance = {'prompt': prompt}
    if previous_video_uri:
        instance['video'] = {'uri': previous_video_uri}

    body = {
        'instances': [instance],
        'parameters': {
            'durationSeconds': duration_seconds,
            'aspectRatio': aspect_ratio,
            'sampleCount': 1,
        },
    }

    for attempt in range(3):
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        resp_headers = dict(resp.headers)
        if resp.status_code == 429:
            update_ratelimit_from_headers(resp_headers)
            mark_quota_exhausted(resp.text)
            raise QuotaExceededError(resp.text, response_headers=resp_headers)
        if resp.status_code == 200:
            operation = resp.json()
            operation_name = operation.get('name')
            if not operation_name:
                raise Exception(f'No operation name in response: {operation}')
            op_data = _poll_operation(operation_name, effective_key, poll_interval)
            generated_samples = (
                op_data.get('response', {})
                .get('generateVideoResponse', {})
                .get('generatedSamples', [])
            )
            if not generated_samples:
                raise Exception('No video generated: empty predictions')
            video_info = generated_samples[0].get('video', {})
            video_uri = video_info.get('uri', '')
            if video_uri:
                return video_uri, resp_headers
            raise Exception(f'Unexpected response format: {list(op_data.get("response", {}).keys())}')
        if resp.status_code == 400 and 'high demand' in resp.text and attempt < 2:
            time.sleep(10 * (attempt + 1))
            continue
        raise Exception(f'Veo API error {resp.status_code}: {resp.text}')


EXTENSION_BLACKLIST = {'veo-3.1-lite-generate-preview'}


def generate_video_from_text(prompt, duration_seconds=8, aspect_ratio='16:9', poll_interval=5, model_name=None, api_key=None, target_duration_seconds=None):
    model = model_name or 'veo-3.1-generate-preview'
    effective_key = api_key or GEMINI_STUDIO_KEY

    if aspect_ratio not in VEO_SUPPORTED_ASPECT_RATIOS:
        aspect_ratio = '16:9'

    target = target_duration_seconds or duration_seconds
    valid_durations = sorted([4, 6, 8], reverse=True)

    can_extend = model not in EXTENSION_BLACKLIST
    if not can_extend and target > 8:
        target = 8

    clip_duration = max((v for v in valid_durations if v <= target), default=8)
    video_uri, resp_headers = _start_generation(
        prompt, clip_duration, aspect_ratio, effective_key, model
    )
    total_generated = clip_duration

    while can_extend and total_generated < target:
        remaining = target - total_generated
        next_duration = max((v for v in valid_durations if v <= remaining), default=min(valid_durations))
        video_uri, _ = _start_generation(
            prompt, next_duration, aspect_ratio, effective_key, model,
            previous_video_uri=video_uri
        )
        total_generated += next_duration

    return _download_from_uri(video_uri, prompt, effective_key), resp_headers


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
