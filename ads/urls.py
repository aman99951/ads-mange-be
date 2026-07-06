from django.urls import path, include
from rest_framework.routers import DefaultRouter, SimpleRouter
from rest_framework_nested import routers
from . import views

router = DefaultRouter()
router.register(r'target-areas', views.TargetAreaViewSet, basename='target-area')
router.register(r'target-audiences', views.TargetAudienceViewSet, basename='target-audience')
router.register(r'languages', views.LanguageViewSet, basename='language')
router.register(r'ads', views.AdViewSet, basename='ad')
router.register(r'developer/ads', views.DeveloperAdViewSet, basename='developer-ad')
router.register(r'developer/apps', views.DeveloperAppViewSet, basename='developer-app')

ads_router = routers.NestedDefaultRouter(router, r'ads', lookup='ad')
ads_router.register(r'video-feedback', views.VideoFeedbackViewSet, basename='ad-video-feedback')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(ads_router.urls)),
    path('admin/target-areas/', views.admin_target_areas, name='admin-target-areas'),
    path('enhance-prompt/', views.enhance_prompt, name='enhance-prompt'),
    path('public/ads/', views.public_ads, name='public-ads'),
    path('models/', views.available_models, name='available-models'),
    path('usage-stats/', views.api_usage_stats, name='api-usage-stats'),
    path('recent-media/', views.recent_media, name='recent-media'),
    path('creative-sessions/', views.creative_sessions_list, name='creative-sessions-list'),
    path('creative-sessions/<int:pk>/', views.creative_session_detail, name='creative-session-detail'),
    path('creative-sessions/<int:pk>/add-event/', views.creative_session_add_event, name='creative-session-add-event'),
]
