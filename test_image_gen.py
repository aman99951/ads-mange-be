"""
Test image generation using low model via OpenRouter (with limited tokens)
Saves output to test_images/ folder
"""
import os
import sys
import base64
import json
import requests
import re
from pathlib import Path

env_path = Path(__file__).parent / '.env'
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

OR_KEY = os.environ.get('OPENROUTER_API_KEY')
OUTPUT_DIR = Path(__file__).parent / 'test_images'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PROMPT = 'A cute orange cat sitting on a windowsill, digital art style'

# The OpenRouter account has limited credits.
# Error showed: flash-lite can afford 8861 tokens, 2.5-flash can afford 5317 tokens
# We try with low max_tokens to stay within budget
print('=== Testing OpenRouter Image Generation (low tokens) ===')
print(f'Prompt: "{PROMPT}"')

models_and_limits = [
    ('google/gemini-3.1-flash-lite-image', 8000),
    ('google/gemini-2.5-flash-image', 5000),
    ('google/gemini-3.1-flash-image', 4000),
]

for model, max_tokens in models_and_limits:
    print(f'\n--- Model: {model} (max_tokens={max_tokens}) ---')
    url = 'https://openrouter.ai/api/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {OR_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'http://localhost:8000',
        'X-Title': 'AMS Test',
    }
    body = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': PROMPT}],
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=180)
        print(f'Status: {resp.status_code}')
        if resp.status_code == 200:
            data = resp.json()
            choice = data.get('choices', [{}])[0]
            msg = choice.get('message', {})
            content = msg.get('content', '')
            
            img_match = re.search(r'data:image/\w+;base64,([A-Za-z0-9+/=]+)', content)
            if img_match:
                raw = base64.b64decode(img_match.group(1))
                model_short = model.replace('/', '_').replace('google_', '')
                out = OUTPUT_DIR / f'test_{model_short}.jpg'
                out.write_bytes(raw)
                print(f'SUCCESS! Saved to {out} ({len(raw)} bytes)')
                continue
            
            url_match = re.search(r'https?://[^\s]+\.(jpg|jpeg|png|webp)', content)
            if url_match:
                img_url = url_match.group(0)
                print(f'Got image URL: {img_url[:100]}...')
                img_resp = requests.get(img_url, timeout=60)
                if img_resp.status_code == 200:
                    model_short = model.replace('/', '_').replace('google_', '')
                    out = OUTPUT_DIR / f'test_{model_short}.jpg'
                    out.write_bytes(img_resp.content)
                    print(f'SUCCESS! Saved to {out} ({len(img_resp.content)} bytes)')
                    continue
            
            print(f'Finish reason: {choice.get("finish_reason", "")}')
            print(f'Usage: {data.get("usage", {})}')
            if content:
                print(f'Response (first 500 chars):\n{content[:500]}')
            else:
                print('No content in response')
        else:
            err = resp.text[:500]
            print(f'Error: {err}')
    except Exception as e:
        print(f'Exception: {e}')

# Also try OpenRouter's /api/v1/completions endpoint if chat doesn't work
print('\n--- Trying OpenRouter completions endpoint (image generation) ---')
url = 'https://openrouter.ai/api/v1/completions'
headers = {
    'Authorization': f'Bearer {OR_KEY}',
    'Content-Type': 'application/json',
}
body = {
    'model': 'google/gemini-3.1-flash-lite-image',
    'prompt': PROMPT,
    'max_tokens': 8000,
}
try:
    resp = requests.post(url, headers=headers, json=body, timeout=180)
    print(f'Status: {resp.status_code}')
    if resp.status_code == 200:
        data = resp.json()
        print(f'Response keys: {list(data.keys())}')
        print(f'Response: {json.dumps(data, indent=2)[:500]}')
    else:
        print(f'Error: {resp.text[:500]}')
except Exception as e:
    print(f'Exception: {e}')

print('\nDone! Check test_images/ folder for any generated images.')
print('If no images were generated, the API keys need more credits.')
