from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'target-areas', views.TargetAreaViewSet, basename='target-area')
router.register(r'target-audiences', views.TargetAudienceViewSet, basename='target-audience')
router.register(r'languages', views.LanguageViewSet, basename='language')
router.register(r'ads', views.AdViewSet, basename='ad')
router.register(r'developer/ads', views.DeveloperAdViewSet, basename='developer-ad')
router.register(r'developer/apps', views.DeveloperAppViewSet, basename='developer-app')

urlpatterns = [
    path('', include(router.urls)),
    path('admin/target-areas/', views.admin_target_areas, name='admin-target-areas'),
    path('enhance-prompt/', views.enhance_prompt, name='enhance-prompt'),
    path('public/ads/', views.public_ads, name='public-ads'),
]
