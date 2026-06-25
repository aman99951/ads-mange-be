import time
import json
import requests
from django.conf import settings
from django.core.cache import cache

GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

CACHE_KEY_RATELIMIT = 'google_ratelimit_headers'
CACHE_KEY_EXHAUSTED = 'google_quota_exhausted'
CACHE_KEY_ERROR = 'google_quota_error'


class QuotaExceededError(Exception):
    def __init__(self, message, response_headers=None):
        self.response_headers = response_headers or {}
        super().__init__(message)


def mark_quota_exhausted(response_body=None):
    cache.set(CACHE_KEY_EXHAUSTED, True, 300)
    if response_body:
        try:
            data = json.loads(response_body) if isinstance(response_body, str) else response_body
            msg = data.get('error', {}).get('message', '') or data.get('error', {}).get('message', '')
            if msg:
                cache.set(CACHE_KEY_ERROR, msg, 300)
        except (json.JSONDecodeError, AttributeError):
            cache.set(CACHE_KEY_ERROR, str(response_body)[:200], 300)


def is_quota_exhausted():
    return cache.get(CACHE_KEY_EXHAUSTED, False)


def get_quota_error():
    return cache.get(CACHE_KEY_ERROR, '')


def clear_quota_exhausted():
    cache.delete(CACHE_KEY_EXHAUSTED)
    cache.delete(CACHE_KEY_ERROR)


def update_ratelimit_from_headers(headers):
    info = {}
    for h in ['x-ratelimit-limit-requests', 'x-ratelimit-remaining-requests',
              'x-ratelimit-limit-tokens', 'x-ratelimit-remaining-tokens']:
        val = headers.get(h)
        if val is not None:
            info[h] = int(val)

    for h in ['retry-after', 'retry-after-ms']:
        val = headers.get(h)
        if val is not None:
            info[h] = val

    if info:
        info['timestamp'] = time.time()
        cache.set(CACHE_KEY_RATELIMIT, info, 60)
    return info


def get_cached_ratelimit():
    return cache.get(CACHE_KEY_RATELIMIT)
