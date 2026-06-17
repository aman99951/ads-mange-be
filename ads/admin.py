from django.contrib import admin
from .models import TargetArea, TargetAudience, Language, Ad, AdIteration, AdLanguageAsset, DeveloperApp, AdDeveloperPush


@admin.register(TargetArea)
class TargetAreaAdmin(admin.ModelAdmin):
    list_display = ['state', 'city', 'locality']
    list_filter = ['state', 'city']
    search_fields = ['state', 'city', 'locality']


@admin.register(TargetAudience)
class TargetAudienceAdmin(admin.ModelAdmin):
    list_display = ['profile', 'age_min', 'age_max']


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['name']


class AdLanguageAssetInline(admin.TabularInline):
    model = AdLanguageAsset
    extra = 0


class AdIterationInline(admin.TabularInline):
    model = AdIteration
    extra = 0


@admin.register(AdLanguageAsset)
class AdLanguageAssetAdmin(admin.ModelAdmin):
    list_display = ['ad', 'language', 'status', 'created_at']
    list_filter = ['status']


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ['title', 'client', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['title', 'client__mobile']
    inlines = [AdLanguageAssetInline, AdIterationInline]


@admin.register(DeveloperApp)
class DeveloperAppAdmin(admin.ModelAdmin):
    list_display = ['app_name', 'developer', 'app_type', 'is_active']
    list_filter = ['app_type', 'is_active']


@admin.register(AdDeveloperPush)
class AdDeveloperPushAdmin(admin.ModelAdmin):
    list_display = ['ad', 'app', 'pushed_at']
