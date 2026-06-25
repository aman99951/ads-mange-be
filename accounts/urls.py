from django.urls import path
from . import views

urlpatterns = [
    path('send-otp/', views.send_otp, name='send-otp'),
    path('verify-otp/', views.verify_otp, name='verify-otp'),
    path('register/', views.register, name='register'),
    path('create-manager/', views.create_manager, name='create-manager'),
    path('managers/', views.list_managers, name='list-managers'),
    path('manager-login/', views.manager_login, name='manager-login'),
    path('developer-register/', views.developer_register, name='developer-register'),
    path('developer-login/', views.developer_login, name='developer-login'),
    path('manager-api-key/', views.manager_api_key, name='manager-api-key'),
]
