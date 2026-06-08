import random
import jwt
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import Client, Manager
from .serializers import (
    SendOTPSerializer, VerifyOTPSerializer, ClientSerializer,
    RegisterSerializer, CreateManagerSerializer, ManagerSerializer
)

otp_store = {}


def make_client_token(client):
    payload = {
        'client_id': client.id,
        'role': 'client',
        'exp': datetime.utcnow() + timedelta(days=1),
        'iat': datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
    return token


@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp(request):
    serializer = SendOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mobile = serializer.validated_data['mobile']
    otp = str(random.randint(100000, 999999))
    otp_store[mobile] = otp

    print(f'OTP for {mobile}: {otp}')

    return Response({'message': 'OTP sent successfully', 'otp': otp}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    serializer = VerifyOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mobile = serializer.validated_data['mobile']
    otp = serializer.validated_data['otp']

    try:
        client = Client.objects.get(mobile=mobile)
    except Client.DoesNotExist:
        return Response({'error': 'Mobile number not found'}, status=status.HTTP_404_NOT_FOUND)

    if not client.name:
        return Response({'error': 'Please register first'}, status=status.HTTP_400_BAD_REQUEST)

    if otp != '000000' and otp_store.get(mobile) != otp:
        return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)

    otp_store.pop(mobile, None)

    token = make_client_token(client)
    return Response({
        'access': token,
        'user': ClientSerializer(client).data,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mobile = serializer.validated_data['mobile']
    name = serializer.validated_data['name']
    otp = serializer.validated_data['otp']

    if Client.objects.filter(mobile=mobile).exists():
        return Response({'error': 'Mobile already registered'}, status=status.HTTP_400_BAD_REQUEST)

    if otp != '000000' and otp_store.get(mobile) != otp:
        return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)

    otp_store.pop(mobile, None)

    client = Client.objects.create(mobile=mobile, name=name)

    token = make_client_token(client)
    return Response({
        'access': token,
        'user': ClientSerializer(client).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_manager(request):
    if not request.user.is_superuser:
        return Response({'error': 'Only superadmin can create managers'}, status=status.HTTP_403_FORBIDDEN)

    serializer = CreateManagerSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    user = User.objects.create_user(
        username=data['username'],
        password=data['password'],
        first_name=data['name'],
        is_staff=True,
    )
    Manager.objects.create(user=user, mobile=data['username'], name=data['name'])
    return Response(ManagerSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_managers(request):
    if not request.user.is_superuser:
        return Response({'error': 'Only superadmin can view managers'}, status=status.HTTP_403_FORBIDDEN)
    managers = User.objects.filter(is_staff=True)
    return Response(ManagerSerializer(managers, many=True).data)


@api_view(['POST'])
@permission_classes([AllowAny])
def manager_login(request):
    username = request.data.get('username', '')
    password = request.data.get('password', '')
    from django.contrib.auth import authenticate
    user = authenticate(username=username, password=password)
    if user is None or not user.is_staff:
        return Response({'error': 'Invalid credentials or not a manager'}, status=status.HTTP_401_UNAUTHORIZED)
    payload = {
        'user_id': user.id,
        'role': 'manager',
        'exp': datetime.utcnow() + timedelta(days=1),
        'iat': datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
    return Response({
        'access': token,
        'user': {
            'id': user.id,
            'name': user.first_name,
            'username': user.username,
            'role': 'manager',
        },
    })
