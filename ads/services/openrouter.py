"""
OpenRouter AI service for enhancing image/video generation prompts.

Supports multilingual input — detects the user's language and generates
an enhanced prompt in the SAME language, with rich detail suitable for
Imagen / Veo generation. Also generates a negative prompt.
"""

import os
import json
import re
import requests
from django.conf import settings

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY') or getattr(settings, 'OPENROUTER_API_KEY', '')
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'


def _detect_model():
    return 'openrouter/free'


def _build_system_prompt(media_type, width, height):
    is_image = media_type == 'image'
    media = "image" if is_image else "video"
    camera_detail = "shot on 85mm lens, shallow depth of field" if is_image else "shot on Red Komodo, 24fps, cinematic movement"
    aspect = f"{width}:{height}" if width and height else "1:1"

    return f"""You are an expert AI prompt engineer for {media} generation models (Imagen, Veo, DALL-E, Midjourney).

Your task: Take a user's raw prompt and produce TWO things — an enhanced prompt and a negative prompt.

## CRITICAL RULES:

1. **PRESERVE THE USER'S LANGUAGE**: If the user writes in Hindi, Tamil, Bengali, Marathi, Gujarati, Telugu, Kannada, Malayalam, Urdu, Punjabi, or ANY other language — you MUST output BOTH prompts in THAT SAME LANGUAGE. Do NOT switch to English unless the user's prompt is in English.

2. **CULTURAL ACCURACY**: When the prompt is in a local Indian language, use culturally appropriate references, contexts, and terminology relevant to that language's region.

3. **ENHANCED PROMPT**: Add vivid details about lighting, color palette, composition, mood/atmosphere, style references, camera ({camera_detail}), textures. Target aspect ratio is {aspect}. Aim for 2-4 sentences.

4. **NEGATIVE PROMPT**: Generate a comma-separated list of things to avoid. Include common issues like: blurry, low quality, distorted, bad anatomy, extra limbs, ugly, deformed, watermark, text, signature, oversaturated, underexposed, grainy, noisy, pixelated, unnatural colors. Tailor these to the specific content of the prompt.

5. **FORMAT**: You MUST return your response in EXACTLY this format (no extra text, no markdown):
ENHANCED_PROMPT: <the enhanced prompt>
NEGATIVE_PROMPT: <comma-separated list of negative elements>"""


def _strip_safety_lines(text):
    """Remove unwanted safety annotations and disclaimers from AI output."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^(User\s+)?Safety[:\s].*|^(Note|Disclaimer|Warning)[:\s].*|^\[.*(safe|unsafe|harmful).*\]', stripped, re.IGNORECASE):
            continue
        cleaned.append(line)
    result = '\n'.join(cleaned).strip()
    # Also strip trailing standalone annotations that might appear at end
    result = re.sub(r'\n+User\s+Safety\s*:\s*\w+', '', result)
    return result.strip()


def enhance_prompt(user_prompt, media_type='image', width=1024, height=1024):
    """
    Send the user's prompt to OpenRouter and return an enhanced version
    along with a negative prompt.
    
    Returns a dict: { 'enhanced': str, 'negative_prompt': str }
    """
    if not OPENROUTER_API_KEY:
        raise Exception('OPENROUTER_API_KEY is not configured')

    system_prompt = _build_system_prompt(media_type, width, height)

    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://codebuff.ai',
        'X-Title': 'MG-Techno-Pro Creative Studio',
    }

    media_label = "image" if media_type == "image" else "video"

    body = {
        'model': _detect_model(),
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'Enhance this {media_label} generation prompt: "{user_prompt}"'},
        ],
        'temperature': 0.3,
        'max_tokens': 600,
    }

    try:
        resp = requests.post(
            f'{OPENROUTER_BASE_URL}/chat/completions',
            headers=headers,
            json=body,
            timeout=30,
        )
    except requests.exceptions.Timeout:
        raise Exception('OpenRouter request timed out. Please try again.')
    except requests.exceptions.ConnectionError:
        raise Exception('Could not connect to OpenRouter. Check your network connection.')

    if resp.status_code != 200:
        error_detail = ''
        try:
            error_detail = resp.json().get('error', {}).get('message', resp.text[:500])
        except Exception:
            error_detail = resp.text[:500]
        raise Exception(f'OpenRouter API error {resp.status_code}: {error_detail}')

    try:
        result = resp.json()
        content = result['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise Exception(f'Failed to parse OpenRouter response: {str(e)}')

    # Parse the structured response
    enhanced = ''
    negative = ''

    # Try to extract ENHANCED_PROMPT and NEGATIVE_PROMPT sections
    enhanced_match = re.search(r'ENHANCED_PROMPT:\s*(.+?)(?=\nNEGATIVE_PROMPT:|$)', content, re.DOTALL)
    negative_match = re.search(r'NEGATIVE_PROMPT:\s*(.+?)(?=\n[A-Z][a-z]+\s*:|$)', content, re.DOTALL)

    if enhanced_match:
        enhanced = enhanced_match.group(1).strip().strip('"').strip("'").strip()
    else:
        enhanced = content.strip().strip('"').strip("'").strip()

    if negative_match:
        negative = negative_match.group(1).strip().strip('"').strip("'").strip()

    # Strip unwanted safety/disclaimer lines from enhanced prompt
    enhanced = _strip_safety_lines(enhanced)

    # If we got no negative prompt from the AI, provide a sensible default
    if not negative:
        if media_type == 'image':
            negative = 'blurry, low quality, distorted, ugly, deformed, watermark, text, signature, oversaturated, underexposed, grainy, noisy, pixelated, unnatural colors, bad anatomy, extra limbs, cropped, out of frame'
        else:
            negative = 'blurry, low quality, distorted, ugly, watermark, text, jittery, shaky, poor lighting, overexposed, underexposed, grainy, noisy, flickering, bad transitions, unnatural motion'

    return {
        'enhanced': enhanced,
        'negative_prompt': negative,
    }
