import uuid
from django.db import models
from django.contrib.auth.models import User


class Client(models.Model):
    mobile = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_authenticated = True
    is_anonymous = False
    is_staff = False

    def __str__(self):
        return f'{self.name or "?"} ({self.mobile})'


class Manager(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    mobile = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=255)
    google_api_key = models.CharField(max_length=200, blank=True, default='')

    def __str__(self):
        return f'{self.name} ({self.mobile})'


class Developer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=255)
    website = models.URLField(blank=True)
    api_key = models.CharField(max_length=100, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.company_name} ({self.user.username})'
