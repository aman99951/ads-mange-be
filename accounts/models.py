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

    def __str__(self):
        return f'{self.name} ({self.mobile})'
