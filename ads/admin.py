from django.contrib import admin
from .models import TargetArea, TargetAudience, Ad, AdIteration


@admin.register(TargetArea)
class TargetAreaAdmin(admin.ModelAdmin):
    list_display = ['state', 'city', 'locality']
    list_filter = ['state', 'city']
    search_fields = ['state', 'city', 'locality']


@admin.register(TargetAudience)
class TargetAudienceAdmin(admin.ModelAdmin):
    list_display = ['profile', 'age_min', 'age_max']


class AdIterationInline(admin.TabularInline):
    model = AdIteration
    extra = 0


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ['title', 'client', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['title', 'client__mobile']
    inlines = [AdIterationInline]
