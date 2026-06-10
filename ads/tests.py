import jwt
from datetime import datetime, timedelta
from django.conf import settings
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import Client, Manager
from .models import TargetArea, TargetAudience, Ad


class AdsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.target_areas_url = '/api/target-areas/'
        self.target_audiences_url = '/api/target-audiences/'
        self.ads_url = '/api/ads/'
        self.admin_areas_url = '/api/admin/target-areas/'

        self.client_user = Client.objects.create(mobile='9999999990', name='Test Client')
        self.client_token = self._make_client_token(self.client_user)

        self.staff_user = User.objects.create_user(username='staff', password='pass123', is_staff=True)
        self.manager = Manager.objects.create(user=self.staff_user, mobile='staff', name='Staff')
        self.staff_token = self._make_manager_token(self.staff_user)

        self.superuser = User.objects.create_superuser(username='super', password='pass123')
        self.super_token = self._make_manager_token(self.superuser)

        self.area = TargetArea.objects.create(state='Tamil Nadu', city='Chennai', locality='T Nagar')
        self.area2 = TargetArea.objects.create(state='Tamil Nadu', city='Chennai', locality='Velachery')
        self.audience = TargetAudience.objects.create(age_min=18, age_max=35, profile='Engineers')

    def _make_client_token(self, client):
        payload = {
            'client_id': client.id, 'role': 'client',
            'exp': datetime.utcnow() + timedelta(days=1),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    def _make_manager_token(self, user):
        payload = {
            'user_id': user.id, 'role': 'manager',
            'exp': datetime.utcnow() + timedelta(days=1),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    # ─── Target Area Tests ───

    def test_list_target_areas(self):
        self._auth(self.client_token)
        response = self.client.get(self.target_areas_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_target_areas_unauthenticated(self):
        response = self.client.get(self.target_areas_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_target_area_states(self):
        self._auth(self.client_token)
        response = self.client.get(f'{self.target_areas_url}states/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Tamil Nadu', response.data)

    def test_target_area_cities(self):
        self._auth(self.client_token)
        response = self.client.get(f'{self.target_areas_url}cities/', {'state': 'Tamil Nadu'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Chennai', response.data)

    def test_target_area_cities_missing_state(self):
        self._auth(self.client_token)
        response = self.client.get(f'{self.target_areas_url}cities/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_target_area_localities(self):
        self._auth(self.client_token)
        response = self.client.get(f'{self.target_areas_url}localities/', {'state': 'Tamil Nadu', 'city': 'Chennai'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_target_area_localities_missing_params(self):
        self._auth(self.client_token)
        response = self.client.get(f'{self.target_areas_url}localities/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─── Target Audience Tests ───

    def test_list_target_audiences(self):
        self._auth(self.client_token)
        response = self.client.get(self.target_audiences_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_create_target_audience_as_admin(self):
        self._auth(self.staff_token)
        payload = {'age_min': 25, 'age_max': 50, 'profile': 'Doctors'}
        response = self.client.post(self.target_audiences_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TargetAudience.objects.count(), 2)

    def test_create_target_audience_as_client(self):
        self._auth(self.client_token)
        payload = {'age_min': 25, 'age_max': 50, 'profile': 'Doctors'}
        response = self.client.post(self.target_audiences_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_target_audience_as_admin(self):
        self._auth(self.super_token)
        response = self.client.delete(f'{self.target_audiences_url}{self.audience.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # ─── Ad CRUD Tests ───

    def test_create_ad_as_client(self):
        self._auth(self.client_token)
        payload = {
            'title': 'Test Ad',
            'description': 'A test advertisement',
            'target_area_ids': [self.area.id],
            'target_audience_ids': [self.audience.id],
        }
        response = self.client.post(self.ads_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Test Ad')
        self.assertEqual(Ad.objects.count(), 1)

    def test_create_ad_without_auth(self):
        payload = {'title': 'No Auth Ad'}
        response = self.client.post(self.ads_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_ads_as_client(self):
        self._auth(self.client_token)
        Ad.objects.create(client=self.client_user, title='My Ad')
        response = self.client.get(self.ads_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_list_ads_as_admin_sees_all(self):
        self._auth(self.staff_token)
        other = Client.objects.create(mobile='9999999991', name='Other')
        Ad.objects.create(client=self.client_user, title='Ad 1')
        Ad.objects.create(client=other, title='Ad 2')
        response = self.client.get(self.ads_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_get_ad_detail(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Detail Ad')
        ad.target_areas.add(self.area)
        ad.target_audiences.add(self.audience)
        response = self.client.get(f'{self.ads_url}{ad.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Detail Ad')
        self.assertEqual(len(response.data['target_areas']), 1)

    def test_update_ad(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Original')
        response = self.client.patch(f'{self.ads_url}{ad.id}/', {'title': 'Updated'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated')

    def test_client_cannot_see_other_clients_ad(self):
        self._auth(self.client_token)
        other = Client.objects.create(mobile='9999999992', name='Other')
        ad = Ad.objects.create(client=other, title='Other Ad')
        response = self.client.get(f'{self.ads_url}{ad.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ─── Submit for Approval Tests ───

    def test_submit_for_approval(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Submit Ad', status='draft')
        response = self.client.post(f'{self.ads_url}{ad.id}/submit_for_approval/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ad.refresh_from_db()
        self.assertEqual(ad.status, 'pending_approval')

    def test_submit_non_draft_ad(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Already Submitted', status='pending_approval')
        response = self.client.post(f'{self.ads_url}{ad.id}/submit_for_approval/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_other_clients_ad(self):
        self._auth(self.client_token)
        other = Client.objects.create(mobile='9999999993', name='Other')
        ad = Ad.objects.create(client=other, title='Not Mine', status='draft')
        response = self.client.post(f'{self.ads_url}{ad.id}/submit_for_approval/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ─── Approve/Reject Tests ───

    def test_approve_ad(self):
        self._auth(self.staff_token)
        ad = Ad.objects.create(client=self.client_user, title='Approve Me', status='pending_approval')
        response = self.client.post(f'{self.ads_url}{ad.id}/approve/', {'admin_feedback': 'Looks good'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ad.refresh_from_db()
        self.assertEqual(ad.status, 'approved')
        self.assertEqual(ad.admin_feedback, 'Looks good')

    def test_approve_by_non_staff(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Fail Approve', status='pending_approval')
        response = self.client.post(f'{self.ads_url}{ad.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reject_ad(self):
        self._auth(self.staff_token)
        ad = Ad.objects.create(client=self.client_user, title='Reject Me', status='pending_approval')
        response = self.client.post(f'{self.ads_url}{ad.id}/reject/', {'admin_feedback': 'Needs work'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ad.refresh_from_db()
        self.assertEqual(ad.status, 'rejected')
        self.assertEqual(ad.admin_feedback, 'Needs work')

    # ─── Iteration Tests ───

    def test_add_iteration(self):
        self._auth(self.staff_token)
        ad = Ad.objects.create(client=self.client_user, title='Iterate', status='rejected')
        response = self.client.post(f'{self.ads_url}{ad.id}/add_iteration/', {'feedback': 'Try a different angle'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ad.iterations.count(), 1)

    def test_add_iteration_as_client(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Client Iteration', status='rejected')
        response = self.client.post(f'{self.ads_url}{ad.id}/add_iteration/', {'feedback': 'Revised version'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ad.iterations.count(), 1)

    # ─── Download Tests ───

    def test_download_final_not_available(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='No Video')
        response = self.client.get(f'{self.ads_url}{ad.id}/download_final/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ─── Generate Video Tests ───

    def test_generate_video_by_non_staff(self):
        self._auth(self.client_token)
        ad = Ad.objects.create(client=self.client_user, title='Gen Video', status='approved')
        response = self.client.post(f'{self.ads_url}{ad.id}/generate_video/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_generate_video_not_approved(self):
        self._auth(self.staff_token)
        ad = Ad.objects.create(client=self.client_user, title='Not Approved', status='draft')
        response = self.client.post(f'{self.ads_url}{ad.id}/generate_video/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_video_no_content(self):
        self._auth(self.staff_token)
        ad = Ad.objects.create(client=self.client_user, title='', status='approved')
        response = self.client.post(f'{self.ads_url}{ad.id}/generate_video/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_video_starts_generation(self):
        self._auth(self.staff_token)
        ad = Ad.objects.create(client=self.client_user, title='Test Gen', description='A video about testing', status='approved')
        response = self.client.post(f'{self.ads_url}{ad.id}/generate_video/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('started', response.data['message'])

    # ─── Admin Target Areas Tests ───

    def test_admin_list_target_areas(self):
        self._auth(self.staff_token)
        response = self.client.get(self.admin_areas_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_admin_create_target_area(self):
        self._auth(self.staff_token)
        payload = {'state': 'Karnataka', 'city': 'Bangalore', 'locality': 'Koramangala'}
        response = self.client.post(self.admin_areas_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TargetArea.objects.count(), 3)

    def test_admin_areas_unauthorized(self):
        response = self.client.get(self.admin_areas_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
