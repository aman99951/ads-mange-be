from django.db import models


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


class Ad(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
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
    asset = models.FileField(upload_to='ad_assets/', blank=True, null=True,
                             help_text='Upload image/video or leave blank to generate from text')
    text_content = models.TextField(blank=True, help_text='Text content for ad generation')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    admin_feedback = models.TextField(blank=True)
    final_asset = models.FileField(upload_to='final_ads/', blank=True, null=True)
    generation_error = models.TextField(blank=True, help_text='Error message from video generation, if any')
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
