import jwt
from datetime import datetime, timedelta
from django.conf import settings
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from .models import Client, Manager


class AccountsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.register_url = '/api/auth/register/'
        self.send_otp_url = '/api/auth/send-otp/'
        self.verify_otp_url = '/api/auth/verify-otp/'
        self.manager_login_url = '/api/auth/manager-login/'
        self.create_manager_url = '/api/auth/create-manager/'
        self.managers_url = '/api/auth/managers/'

    def make_client_token(self, client):
        payload = {
            'client_id': client.id,
            'role': 'client',
            'exp': datetime.utcnow() + timedelta(days=1),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    def make_manager_token(self, user):
        payload = {
            'user_id': user.id,
            'role': 'manager',
            'exp': datetime.utcnow() + timedelta(days=1),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    # ─── Register Tests ───

    def test_register_success(self):
        payload = {'mobile': '9999999990', 'name': 'Test User', 'otp': '000000'}
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertEqual(response.data['user']['mobile'], '9999999990')
        self.assertEqual(response.data['user']['name'], 'Test User')
        self.assertTrue(Client.objects.filter(mobile='9999999990').exists())

    def test_register_duplicate_mobile(self):
        Client.objects.create(mobile='9999999991', name='Existing')
        payload = {'mobile': '9999999991', 'name': 'Duplicate', 'otp': '000000'}
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_without_otp(self):
        payload = {'mobile': '9999999992', 'name': 'No OTP'}
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_invalid_mobile(self):
        payload = {'mobile': '', 'name': 'Invalid', 'otp': '000000'}
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─── Send OTP Tests ───

    def test_send_otp_success(self):
        payload = {'mobile': '9999999993'}
        response = self.client.post(self.send_otp_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('otp', response.data)

    def test_send_otp_missing_mobile(self):
        response = self.client.post(self.send_otp_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─── Verify OTP Tests ───

    def test_verify_otp_success_with_dev_otp(self):
        client = Client.objects.create(mobile='9999999994', name='Verify Test')
        payload = {'mobile': '9999999994', 'otp': '000000'}
        response = self.client.post(self.verify_otp_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_verify_otp_nonexistent_client(self):
        payload = {'mobile': '9999999995', 'otp': '000000'}
        response = self.client.post(self.verify_otp_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_verify_otp_unregistered_client(self):
        client = Client.objects.create(mobile='9999999996', name='')
        payload = {'mobile': '9999999996', 'otp': '000000'}
        response = self.client.post(self.verify_otp_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_otp_wrong_otp(self):
        Client.objects.create(mobile='9999999997', name='Wrong OTP')
        payload = {'mobile': '9999999997', 'otp': '123456'}
        response = self.client.post(self.verify_otp_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─── Manager Login Tests ───

    def test_manager_login_success(self):
        user = User.objects.create_user(username='manager1', password='pass123', is_staff=True)
        Manager.objects.create(user=user, mobile='9999999998', name='Manager One')
        payload = {'username': 'manager1', 'password': 'pass123'}
        response = self.client.post(self.manager_login_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertEqual(response.data['user']['name'], 'Manager One')

    def test_manager_login_invalid_credentials(self):
        payload = {'username': 'nonexistent', 'password': 'wrong'}
        response = self.client.post(self.manager_login_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_manager_login_non_staff(self):
        user = User.objects.create_user(username='regular', password='pass123', is_staff=False)
        payload = {'username': 'regular', 'password': 'pass123'}
        response = self.client.post(self.manager_login_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ─── Create Manager Tests ───

    def test_create_manager_by_superuser(self):
        superuser = User.objects.create_superuser(username='admin', password='admin123')
        token = self.make_manager_token(superuser)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        payload = {'name': 'New Manager', 'username': 'newmgr', 'password': 'pass123'}
        response = self.client.post(self.create_manager_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Manager.objects.filter(mobile='newmgr').exists())

    def test_create_manager_by_non_superuser(self):
        user = User.objects.create_user(username='staff', password='pass123', is_staff=True)
        Manager.objects.create(user=user, mobile='staff', name='Staff')
        token = self.make_manager_token(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        payload = {'name': 'Should Fail', 'username': 'fail', 'password': 'pass'}
        response = self.client.post(self.create_manager_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_manager_unauthenticated(self):
        payload = {'name': 'No Auth', 'username': 'noauth', 'password': 'pass'}
        response = self.client.post(self.create_manager_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ─── List Managers Tests ───

    def test_list_managers_by_superuser(self):
        superuser = User.objects.create_superuser(username='admin2', password='admin123')
        token = self.make_manager_token(superuser)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.get(self.managers_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_managers_unauthorized(self):
        response = self.client.get(self.managers_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
