import jwt
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import Client, Developer


class ClientJWTAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer realm="api"'

    def authenticate(self, request):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None

        token = auth.split(' ')[1]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token expired')
        except jwt.InvalidTokenError:
            raise AuthenticationFailed('Invalid token')

        role = payload.get('role')

        if role == 'client':
            client_id = payload.get('client_id')
            try:
                client = Client.objects.get(id=client_id)
            except Client.DoesNotExist:
                raise AuthenticationFailed('Client not found')
            return (client, token)

        if role in ('admin', 'superadmin', 'manager'):
            user_id = payload.get('user_id')
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise AuthenticationFailed('User not found')
            return (user, token)

        if role == 'developer':
            user_id = payload.get('user_id')
            try:
                dev = Developer.objects.get(user_id=user_id, is_active=True)
            except Developer.DoesNotExist:
                raise AuthenticationFailed('Developer not found or inactive')
            return (dev.user, token)

        raise AuthenticationFailed('Unknown role')
