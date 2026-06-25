"""
Google AI model configurations for image and video generation.
Centralized list of available models, their API endpoints, and credit costs.
"""

IMAGE_MODELS = [
    {
        'id': 'gemini-2.5-flash-image',
        'name': 'Nano Banana',
        'description': 'Fast, efficient image generation (Gemini 2.5 Flash)',
        'credit_cost': 2,
        'media_type': 'image',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'interactions',
    },
    {
        'id': 'gemini-3.1-flash-image',
        'name': 'Nano Banana 2',
        'description': 'High-efficiency image generation (Gemini 3.1 Flash)',
        'credit_cost': 3,
        'media_type': 'image',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'interactions',
    },
    {
        'id': 'gemini-3-pro-image',
        'name': 'Nano Banana Pro',
        'description': 'Professional quality with advanced reasoning',
        'credit_cost': 5,
        'media_type': 'image',
        'is_premium': True,
        'provider': 'google',
        'api_type': 'interactions',
    },
]

VIDEO_MODELS = [
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
    {
        'id': 'veo-3.0-generate-001',
        'name': 'Veo 3.0',
        'description': 'High-quality video generation',
        'credit_cost': 5,
        'media_type': 'video',
        'is_premium': False,
        'provider': 'google',
        'api_type': 'predictLongRunning',
    },
    {
        'id': 'veo-3.0-fast-001',
        'name': 'Veo 3.0 Fast',
        'description': 'Faster video generation, good quality',
        'credit_cost': 4,
        'media_type': 'video',
        'is_premium': False,
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
