from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'target-areas', views.TargetAreaViewSet, basename='target-area')
router.register(r'target-audiences', views.TargetAudienceViewSet, basename='target-audience')
router.register(r'ads', views.AdViewSet, basename='ad')

urlpatterns = [
    path('', include(router.urls)),
    path('admin/target-areas/', views.admin_target_areas, name='admin-target-areas'),
]
