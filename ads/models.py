from django.db import models
from django.utils import timezone
from django.conf import settings
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


def log_api_usage(model_id, success=True, response_headers=None):
    if response_headers:
        update_ratelimit_from_headers(dict(response_headers))
    return get_remaining_quota()


class ApiUsageLog(models.Model):
    """Tracks each Google API request made for quota management."""
    model_id = models.CharField(max_length=100, help_text='Google model ID used')
    success = models.BooleanField(default=True)
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
        ('expired', 'Expired'),
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
