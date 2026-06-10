import os
import json
import time
import requests
from django.conf import settings
from django.core.files.base import ContentFile


VEO_API_KEY = os.environ.get('VEO_API_KEY') or getattr(settings, 'VEO_API_KEY', '')
VEO_BASE_URL = os.environ.get('VEO_BASE_URL') or 'https://generativelanguage.googleapis.com/v1beta'


def generate_video_from_text(prompt, duration_seconds=8, aspect_ratio='16:9', poll_interval=5):
    model = 'veo-3.0-generate-001'
    url = f'{VEO_BASE_URL}/models/{model}:predictLongRunning'

    headers = {
        'X-Goog-Api-Key': VEO_API_KEY,
        'Content-Type': 'application/json',
    }

    body = {
        'instances': [{
            'prompt': prompt,
        }],
        'parameters': {
            'durationSeconds': duration_seconds,
            'aspectRatio': aspect_ratio,
            'sampleCount': 1,
        },
    }

    resp = requests.post(url, headers=headers, json=body, timeout=60)
    if resp.status_code != 200:
        raise Exception(f'Veo API error {resp.status_code}: {resp.text}')

    operation = resp.json()
    operation_name = operation.get('name')
    if not operation_name:
        raise Exception(f'No operation name in response: {operation}')

    while True:
        op_resp = requests.get(
            f'{VEO_BASE_URL}/{operation_name}',
            headers={'X-Goog-Api-Key': VEO_API_KEY},
            timeout=30,
        )
        if op_resp.status_code != 200:
            raise Exception(f'Veo operation poll error {op_resp.status_code}: {op_resp.text}')

        op_data = op_resp.json()

        if op_data.get('done'):
            if 'error' in op_data:
                err = op_data['error']
                raise Exception(f'Veo generation failed: {err.get("message", str(err))}')

            response_data = op_data.get('response', {})
            predictions = response_data.get('predictions', [])
            if not predictions:
                raise Exception('No video generated: empty predictions')

            prediction = predictions[0]

            if 'video' in prediction:
                import base64
                b64 = prediction['video']
                if isinstance(b64, dict):
                    b64 = b64.get('encodedVideo', '')
                raw = base64.b64decode(b64)
                mime_type = prediction.get('mimeType', 'video/mp4')
                return ContentFile(raw, name=_filename(prompt, mime_type))

            if 'gcsUri' in prediction:
                return _download_from_gcs(prediction['gcsUri'], prompt)

            if 'fileData' in prediction:
                file_uri = prediction['fileData'].get('fileUri', '')
                if file_uri:
                    return _download_from_uri(file_uri, prompt)

            raise Exception(f'Unexpected prediction format: {list(prediction.keys())}')

        time.sleep(poll_interval)


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


def _download_from_uri(file_uri, prompt):
    headers = {'X-Goog-Api-Key': VEO_API_KEY}
    resp = requests.get(file_uri, headers=headers, stream=True, timeout=120)
    if resp.status_code != 200:
        raise Exception(f'Failed to download video from {file_uri}: {resp.status_code}')
    content_type = resp.headers.get('Content-Type', 'video/mp4')
    return ContentFile(resp.content, name=_filename(prompt, content_type))


def _filename(prompt, mime_type):
    ext = mime_type.split('/')[-1] if '/' in mime_type else 'mp4'
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in prompt)[:40].strip()
    return f'veo_{safe}_{int(time.time())}.{ext}'
