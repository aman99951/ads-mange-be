from rest_framework import serializers
from .models import Client, Manager, Developer
from django.contrib.auth.models import User


class SendOTPSerializer(serializers.Serializer):
    mobile = serializers.CharField(max_length=15)


class VerifyOTPSerializer(serializers.Serializer):
    mobile = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ['id', 'mobile', 'name', 'created_at']


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    mobile = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)


class CreateManagerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)


class ManagerSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'is_staff', 'date_joined']
        read_only_fields = ['id', 'is_staff', 'date_joined']


class DeveloperSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Developer
        fields = ['id', 'company_name', 'website', 'api_key', 'username', 'created_at']


class RegisterDeveloperSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)


class DeveloperLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
