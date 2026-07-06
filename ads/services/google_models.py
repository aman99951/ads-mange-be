"""
Google AI model configurations for image and video generation.
Centralized list of available models, their API endpoints, and credit costs.
"""

IMAGE_MODELS = [
    {
        'id': 'gemini-3.1-flash-lite-image',
        'name': 'Gemini 3.1 Flash Lite Image',
        'description': 'Fastest lightweight option — 1 credit',
        'credit_cost': 1,
        'media_type': 'image',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'generateContent',
    },
    {
        'id': 'gemini-2.5-flash-image',
        'name': 'Gemini 2.5 Flash Image',
        'description': 'Fast image generation via Gemini API — 2 credits',
        'credit_cost': 2,
        'media_type': 'image',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'generateContent',
    },
    {
        'id': 'gemini-3.1-flash-image',
        'name': 'Gemini 3.1 Flash Image',
        'description': 'High-efficiency image generation — 3 credits',
        'credit_cost': 3,
        'media_type': 'image',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'generateContent',
    },
    {
        'id': 'gemini-3-pro-image',
        'name': 'Gemini 3 Pro Image',
        'description': 'Professional quality with advanced reasoning — 5 credits',
        'credit_cost': 5,
        'media_type': 'image',
        'is_premium': True,
        'provider': 'google',
        'api_type': 'generateContent',
    },
]

VIDEO_MODELS = [
    {
        'id': 'veo-3.1-lite-generate-preview',
        'name': 'Veo 3.1 Lite',
        'description': 'Fastest, lightweight option',
        'credit_cost': 4,
        'media_type': 'video',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'predictLongRunning',
    },
    {
        'id': 'veo-3.1-fast-generate-preview',
        'name': 'Veo 3.1 Fast',
        'description': 'Faster generation, good quality',
        'credit_cost': 6,
        'media_type': 'video',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'predictLongRunning',
    },
    {
        'id': 'veo-3.1-generate-preview',
        'name': 'Veo 3.1',
        'description': 'Latest cinematic video generation',
        'credit_cost': 8,
        'media_type': 'video',
        'is_premium': True,
        'provider': 'google',
        'api_type': 'predictLongRunning',
    },
]

ALL_MODELS = IMAGE_MODELS + VIDEO_MODELS


def get_model_info(model_id):
    """Get model info by ID. Returns None if not found."""
    for m in ALL_MODELS:
        if m['id'] == model_id:
            return m
    return None


def get_credit_cost(model_id):
    """Get credit cost for a model. Returns None if model not found."""
    model = get_model_info(model_id)
    return model['credit_cost'] if model else None


def is_image_model(model_id):
    """Check if a model is for image generation."""
    model = get_model_info(model_id)
    return model and model['media_type'] == 'image'


def is_video_model(model_id):
    """Check if a model is for video generation."""
    model = get_model_info(model_id)
    return model and model['media_type'] == 'video'
