"""
Test image generation using low model via OpenRouter - debug mode
Saves output to test_images/ folder
"""
import os
import sys
import base64
import json
import requests
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
MODEL = 'google/gemini-2.5-flash-image'

print(f'Model: {MODEL}')
print(f'Prompt: "{PROMPT}"')

url = 'https://openrouter.ai/api/v1/chat/completions'
headers = {
    'Authorization': f'Bearer {OR_KEY}',
    'Content-Type': 'application/json',
    'HTTP-Referer': 'http://localhost:8000',
    'X-Title': 'AMS Test',
}
body = {
    'model': MODEL,
    'max_tokens': 5000,
    'messages': [{'role': 'user', 'content': PROMPT}],
}

resp = requests.post(url, headers=headers, json=body, timeout=180)
print(f'Status: {resp.status_code}')
data = resp.json()

# Dump the full response structure (truncated)
resp_str = json.dumps(data, indent=2)
print(f'\nFull response:\n{resp_str[:3000]}')

# Check if there are images in the response
choice = data.get('choices', [{}])[0]
msg = choice.get('message', {})
print(f'\nMessage keys: {list(msg.keys())}')
print(f'Content type: {type(msg.get("content"))}')
print(f'Content value: {repr(msg.get("content"))[:500]}')

# Check for parts, image_url, etc.
for key in msg:
    print(f'  msg["{key}"] = {repr(msg[key])[:300]}')

# Check finish reason
print(f'Finish reason: {choice.get("finish_reason")}')

# Check usage
print(f'Usage: {json.dumps(data.get("usage", {}), indent=2)}')
