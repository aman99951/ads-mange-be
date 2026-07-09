from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
import uuid
from .services.google_quota import (
    update_ratelimit_from_headers,
    get_cached_ratelimit,
    is_quota_exhausted,
    get_quota_error,
)


def get_remaining_quota():
    result = {
        'exhausted': is_quota_exhausted(),
    }
    error = get_quota_error()
    if error:
        result['error'] = error
    ratelimit = get_cached_ratelimit()
    if ratelimit:
        result['google_rate_limit'] = ratelimit
    return result


def log_api_usage(model_id, success=True, response_headers=None, credit_cost=0):
    # Save a record for actual API call tracking
    ApiUsageLog.objects.create(model_id=model_id, success=success, credit_cost=credit_cost)
    if response_headers:
        update_ratelimit_from_headers(dict(response_headers))
    return get_remaining_quota()


class ApiUsageLog(models.Model):
    """Tracks each Google API request made for quota management."""
    model_id = models.CharField(max_length=100, help_text='Google model ID used')
    success = models.BooleanField(default=True)
    credit_cost = models.IntegerField(default=0, help_text='Credits consumed (0 = free request)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'API Usage Log'
        verbose_name_plural = 'API Usage Logs'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.model_id} at {self.created_at}'


class TargetArea(models.Model):
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    locality = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ['state', 'city', 'locality']

    def __str__(self):
        parts = [self.state, self.city]
        if self.locality:
            parts.append(self.locality)
        return ', '.join(parts)


class TargetAudience(models.Model):
    age_min = models.IntegerField()
    age_max = models.IntegerField()
    profile = models.CharField(max_length=200, help_text='e.g., Electricians, Plumbers, Teachers')

    def __str__(self):
        return f'{self.profile} ({self.age_min}-{self.age_max})'


class Language(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Ad(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('revision_requested', 'Revision Requested'),
        ('expired', 'Expired'),
    ]

    CONTENT_TYPE_CHOICES = [
        ('video', 'Video'),
        ('image', 'Image'),
    ]

    client = models.ForeignKey(
        'accounts.Client',
        on_delete=models.CASCADE,
        related_name='ads'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    target_areas = models.ManyToManyField(TargetArea, blank=True)
    target_audiences = models.ManyToManyField(TargetAudience, blank=True)
    languages = models.ManyToManyField(Language, blank=True)
    asset = models.FileField(upload_to='ad_assets/', blank=True, null=True,
                             help_text='Upload image/video or leave blank to generate from text')
    text_content = models.TextField(blank=True, help_text='Text content for ad generation')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    admin_feedback = models.TextField(blank=True)
    final_asset = models.FileField(upload_to='final_ads/', blank=True, null=True)
    generation_error = models.TextField(blank=True, help_text='Error message from video generation, if any')
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPE_CHOICES, blank=True, default='video',
                                    help_text='Whether to generate a video or image ad')
    content_size = models.CharField(max_length=50, blank=True, default='',
                                    help_text='Desired dimensions e.g. 1920x1080, 1080x1920')
    scheduled_start = models.DateTimeField(blank=True, null=True, help_text='Campaign start date')
    scheduled_end = models.DateTimeField(blank=True, null=True, help_text='Campaign end date')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.title} - {self.client.mobile}'


class AdIteration(models.Model):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name='iterations')
    asset = models.FileField(upload_to='iteration_assets/', blank=True, null=True)
    feedback = models.TextField(blank=True)
    created_by = models.CharField(max_length=20, choices=[
        ('client', 'Client'),
        ('admin', 'Admin'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Iteration {self.id} for {self.ad.title}'


class AdLanguageAsset(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generating', 'Generating'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name='language_assets')
    language = models.ForeignKey(Language, on_delete=models.CASCADE)
    prompt = models.TextField(blank=True, help_text='Prompt used for video generation')
    asset = models.FileField(upload_to='final_ads/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['ad', 'language']

    def __str__(self):
        return f'{self.language.name} asset for {self.ad.title}'


class DeveloperApp(models.Model):
    APP_TYPES = [
        ('website', 'Website'),
        ('mobile', 'Mobile App'),
    ]

    developer = models.ForeignKey(
        'accounts.Developer',
        on_delete=models.CASCADE,
        related_name='apps'
    )
    app_name = models.CharField(max_length=255)
    app_type = models.CharField(max_length=20, choices=APP_TYPES, default='website')
    app_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    rating = models.FloatField(default=0.0)
    api_key = models.CharField(max_length=100, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.app_name} ({self.developer.company_name})'


class AdDeveloperPush(models.Model):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name='developer_pushes')
    app = models.ForeignKey(DeveloperApp, on_delete=models.CASCADE, related_name='ad_pushes')
    pushed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['ad', 'app']
        verbose_name = 'Ad to Developer Push'
        verbose_name_plural = 'Ad to Developer Pushes'

    def __str__(self):
        return f'{self.ad.title} → {self.app.app_name}'


class GeneratedMedia(models.Model):
    MEDIA_TYPES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]

    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name='generated_media'
    )
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES)
    file = models.FileField(upload_to='generated_media/')
    prompt = models.TextField(blank=True)
    model_used = models.CharField(max_length=100, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)
    aspect_ratio = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Generated Media'
        verbose_name_plural = 'Generated Media'

    def __str__(self):
        return f'{self.media_type} - {self.prompt[:40]}'


class CreativeSession(models.Model):
    MEDIA_TYPES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]

    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name='creative_sessions'
    )
    title = models.CharField(max_length=255, blank=True,
        help_text='Auto-generated from first prompt')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES, default='image')
    settings = models.JSONField(default=dict, blank=True,
        help_text='Session settings: width, height, duration, model, style, etc.')
    current_prompt = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Creative Session'
        verbose_name_plural = 'Creative Sessions'

    def __str__(self):
        return self.title or f'Session {self.id}'


class CreativeSessionEvent(models.Model):
    EVENT_TYPES = [
        ('generate', 'Generation'),
        ('edit_prompt', 'Prompt Edit'),
        ('edit_settings', 'Settings Change'),
        ('delete_asset', 'Asset Deletion'),
        ('merge', 'Video Merge'),
    ]

    session = models.ForeignKey(
        CreativeSession, on_delete=models.CASCADE, related_name='events'
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    prompt = models.TextField(blank=True,
        help_text='Prompt at the time of event')
    settings = models.JSONField(default=dict, blank=True,
        help_text='Settings snapshot at time of event')
    generated_media = models.ForeignKey(
        GeneratedMedia, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='session_events'
    )
    file = models.URLField(max_length=500, blank=True, default='',
        help_text='Direct file URL for events without GeneratedMedia (e.g. merged videos)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Session Event'
        verbose_name_plural = 'Session Events'

    def __str__(self):
        return f'{self.event_type} at {self.created_at}'


class CreditUsageLog(models.Model):
    """Tracks each generation's credit cost per manager per month."""
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name='credit_usage_logs'
    )
    model_id = models.CharField(max_length=100, db_index=True, help_text='Google model ID used')
    credit_cost = models.IntegerField(help_text='Number of credits consumed for this generation')
    media_type = models.CharField(max_length=10, help_text='image or video')
    generated_media = models.ForeignKey(
        'GeneratedMedia', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='credit_logs'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Credit Usage Log'
        verbose_name_plural = 'Credit Usage Logs'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.model_id} ({self.credit_cost} cr) @ {self.created_at.date()}'


class VideoFeedback(models.Model):
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name='video_feedback')
    language_asset = models.ForeignKey(AdLanguageAsset, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='video_feedback',
        help_text='Specific language asset this feedback refers to, if any')
    user_name = models.CharField(max_length=255, blank=True,
        help_text='Display name of the person who left feedback')
    created_by = models.CharField(max_length=20, choices=[
        ('client', 'Client'),
        ('admin', 'Admin'),
    ], default='client')
    comment = models.TextField()
    timestamp_seconds = models.FloatField(null=True, blank=True,
        help_text='Video timestamp in seconds for annotation')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Feedback on {self.ad.title} at {self.timestamp_seconds}s'
