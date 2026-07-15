import csv
import io
import os
import re
import base64
import threading
import time
import requests as http_requests
from urllib.parse import urlparse
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from .models import TargetArea, TargetAudience, Language, Ad, AdIteration, AdLanguageAsset, DeveloperApp, AdDeveloperPush, GeneratedMedia, VideoFeedback, CreativeSession, CreativeSessionEvent, CreditUsageLog, ApiUsageLog, get_remaining_quota
from .serializers import (
    TargetAreaSerializer, TargetAudienceSerializer, LanguageSerializer,
    AdListSerializer, AdDetailSerializer, AdStatusSerializer,
    AdIterationSerializer, AdLanguageAssetSerializer,
    DeveloperAppSerializer, AdDeveloperPushSerializer, PublicAdSerializer,
    DeveloperAdListSerializer, GeneratedMediaSerializer, VideoFeedbackSerializer,
    CreativeSessionListSerializer, CreativeSessionDetailSerializer, CreativeSessionCreateSerializer, CreativeSessionEventSerializer,
    RevisionRequestSerializer,
    CreditUsageLogSerializer, MonthlyCreditStatsSerializer,
    ApiUsageLogSerializer
)
from .services.veo import generate_video_from_text
from .services.imagen import generate_image_from_text
from .services.nano_banana import generate_nano_banana_image
from .services.gemini_image import generate_gemini_image
from .services.openrouter import enhance_prompt as enhance_prompt_service
from .services.google_models import get_model_info, IMAGE_MODELS, VIDEO_MODELS
from .services.google_quota import QuotaExceededError
from accounts.models import Manager
from django.db.models import Sum, Count
from datetime import datetime


def _get_manager_api_key(user):
    try:
        manager = Manager.objects.get(user=user)
        return manager.google_api_key or None
    except Manager.DoesNotExist:
        return None


@api_view(['GET'])
@permission_classes([AllowAny])
def available_models(request):
    """Return list of available Google models with credit costs."""
    return Response({
        'image_models': IMAGE_MODELS,
        'video_models': VIDEO_MODELS,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recent_media(request):
    """Return the most recent generated media for the current user."""
    media = GeneratedMedia.objects.filter(user=request.user)[:20]
    serializer = GeneratedMediaSerializer(media, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_usage_stats(request):
    quota = get_remaining_quota()
    return Response(quota)


class TargetAreaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TargetArea.objects.all()
    serializer_class = TargetAreaSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def states(self, request):
        states = TargetArea.objects.values_list('state', flat=True).distinct()
        return Response(sorted(set(states)))

    @action(detail=False, methods=['get'])
    def cities(self, request):
        state = request.query_params.get('state')
        if not state:
            return Response({'error': 'state parameter required'}, status=400)
        cities = TargetArea.objects.filter(state=state).values_list('city', flat=True).distinct()
        return Response(sorted(set(cities)))

    @action(detail=False, methods=['get'])
    def localities(self, request):
        state = request.query_params.get('state')
        city = request.query_params.get('city')
        if not state or not city:
            return Response({'error': 'state and city parameters required'}, status=400)
        qs = TargetArea.objects.filter(state=state, city=city)
        return Response(TargetAreaSerializer(qs, many=True).data)


class TargetAudienceViewSet(viewsets.ModelViewSet):
    queryset = TargetAudience.objects.all()
    serializer_class = TargetAudienceSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), permissions.IsAdminUser()]


class LanguageViewSet(viewsets.ModelViewSet):
    queryset = Language.objects.all()
    serializer_class = LanguageSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), permissions.IsAdminUser()]


class AdViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return AdListSerializer
        if self.action in ['approve', 'reject']:
            return AdStatusSerializer
        return AdDetailSerializer

    def _auto_expire(self, qs):
        now = timezone.now()
        expired_ids = list(qs.filter(
            scheduled_end__lte=now,
            status__in=['approved', 'pending_approval']
        ).values_list('id', flat=True))
        if expired_ids:
            Ad.objects.filter(id__in=expired_ids).update(status='expired')
        return qs

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_staff', False):
            qs = Ad.objects.all()
        else:
            qs = Ad.objects.filter(client=user)
        return self._auto_expire(qs)

    def perform_create(self, serializer):
        serializer.save(client=self.request.user)

    @action(detail=True, methods=['post'])
    def submit_for_approval(self, request, pk=None):
        ad = self.get_object()
        if ad.client != request.user:
            return Response({'error': 'Not your ad'}, status=403)
        if ad.status != 'draft':
            return Response({'error': 'Ad is not in draft status'}, status=400)
        ad.status = 'pending_approval'
        ad.save()
        return Response({'status': 'pending_approval'})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        serializer = AdStatusSerializer(ad, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(status='approved')
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        serializer = AdStatusSerializer(ad, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(status='rejected')
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    @action(detail=True, methods=['post'])
    def request_revision(self, request, pk=None):
        ad = self.get_object()
        if ad.client != request.user:
            return Response({'error': 'Not your ad'}, status=403)
        if ad.status == 'draft':
            return Response({'error': 'Submit the ad for approval first before requesting a revision'}, status=400)

        feedback_text = request.data.get('feedback', '').strip()
        if not feedback_text:
            return Response({'error': 'Feedback text is required'}, status=400)

        AdIteration.objects.create(
            ad=ad,
            feedback=feedback_text,
            created_by='client'
        )

        ad.status = 'revision_requested'
        ad.save()

        return Response({'status': 'revision_requested'})

    @action(detail=True, methods=['post'])
    def send_back_to_client(self, request, pk=None):
        ad = self.get_object()
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Only managers can send back to client'}, status=403)
        if ad.status not in ('approved', 'expired', 'revision_requested'):
            return Response({'error': 'Ad must be approved, expired, or revision_requested to send back to client'}, status=400)

        feedback_text = request.data.get('feedback', '').strip()
        if not feedback_text:
            return Response({'error': 'Feedback text is required'}, status=400)

        AdIteration.objects.create(
            ad=ad,
            feedback=feedback_text,
            created_by='admin'
        )

        ad.status = 'revision_requested'
        ad.save()

        return Response({'status': 'revision_requested'})

    @action(detail=False, methods=['get'])
    def revision_requests(self, request):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        qs = Ad.objects.filter(status='revision_requested').select_related('client').order_by('-updated_at')
        serializer = RevisionRequestSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def save_generated_assets(self, request, pk=None):
        """Save AI-generated assets from the studio back to this ad.
        Supports both main video (asset_ids) and language-specific videos (language_assets).
        """
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()

        from django.core.files.storage import default_storage
        from django.core.files import File

        saved_count = 0
        lang_saved = []

        # ── Save main video from asset_ids ──
        asset_ids = request.data.get('asset_ids', [])
        if asset_ids:
            media_objects = GeneratedMedia.objects.filter(id__in=asset_ids)
            first_video = media_objects.filter(media_type='video').first()
            if first_video:
                file_path = first_video.file.name if hasattr(first_video.file, 'name') else str(first_video.file)
                if default_storage.exists(file_path):
                    f = default_storage.open(file_path)
                    ad.final_asset.save(f'studio_{first_video.id}_{file_path.split("/")[-1]}', File(f), save=True)
                    saved_count += 1

        # ── Save language-specific assets ──
        language_assets = request.data.get('language_assets', [])
        for item in language_assets:
            lang_id = item.get('language_id')
            media_id = item.get('generated_media_id')
            prompt = item.get('prompt', '')
            if not lang_id or not media_id:
                continue
            try:
                lang = Language.objects.get(id=lang_id)
                media = GeneratedMedia.objects.get(id=media_id)
            except (Language.DoesNotExist, GeneratedMedia.DoesNotExist):
                continue

            # Copy the media file to the language asset
            media_path = media.file.name if hasattr(media.file, 'name') else str(media.file)
            if not default_storage.exists(media_path):
                continue

            asset_obj, _ = AdLanguageAsset.objects.get_or_create(
                ad=ad, language=lang,
                defaults={'status': 'completed', 'prompt': prompt}
            )
            f = default_storage.open(media_path)
            asset_obj.asset.save(f'lang_{lang.id}_{media_id}_{media_path.split("/")[-1]}', File(f), save=True)
            asset_obj.status = 'completed'
            if prompt:
                asset_obj.prompt = prompt
            asset_obj.save()
            lang_saved.append({'language_id': lang.id, 'language_name': lang.name})
            saved_count += 1

        if saved_count == 0:
            return Response({'error': 'No valid assets found to save'}, status=400)

        # Log an iteration
        AdIteration.objects.create(
            ad=ad,
            feedback='Manager updated the ad video from Creative Studio.',
            created_by='admin'
        )

        # Set status to pending_approval so client can review
        ad.status = 'pending_approval'
        ad.save()

        return Response({
            'status': 'pending_approval',
            'message': f'Saved {saved_count} asset(s) to campaign. Client will be notified.',
            'saved_count': saved_count,
            'language_assets_saved': lang_saved,
        })

    @action(detail=True, methods=['post'])
    def add_iteration(self, request, pk=None):
        ad = self.get_object()
        serializer = AdIterationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(ad=ad, created_by='admin' if getattr(request.user, 'is_staff', False) else 'client')
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    @action(detail=True, methods=['get'])
    def download_final(self, request, pk=None):
        ad = self.get_object()
        asset_id = request.query_params.get('asset_id')
        if asset_id:
            try:
                asset_obj = ad.language_assets.get(id=asset_id)
                if not asset_obj.asset:
                    return Response({'error': 'No asset available for this language'}, status=404)
                return Response({'url': request.build_absolute_uri(asset_obj.asset.url)})
            except AdLanguageAsset.DoesNotExist:
                return Response({'error': 'Asset not found'}, status=404)
        if not ad.final_asset:
            return Response({'error': 'No final asset available'}, status=404)
        return Response({'url': request.build_absolute_uri(ad.final_asset.url)})

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload_asset(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        if ad.status != 'approved':
            return Response({'error': 'Ad must be approved first'}, status=400)

        file = request.FILES.get('file') or request.data.get('file')
        if not file:
            return Response({'error': 'file is required'}, status=400)

        ext = os.path.splitext(file.name)[1] or '.mp4'
        safe_name = f'upload_{ad.id}_{int(time.time())}{ext}'

        language_id = request.data.get('language_id')
        if language_id:
            try:
                language = Language.objects.get(id=language_id)
            except Language.DoesNotExist:
                return Response({'error': 'Invalid language_id'}, status=400)
            asset_obj, _ = AdLanguageAsset.objects.get_or_create(
                ad=ad, language=language,
                defaults={'status': 'completed', 'prompt': ''}
            )
            asset_obj.asset.save(safe_name, file, save=True)
            asset_obj.status = 'completed'
            asset_obj.save()
            return Response({'message': f'Asset uploaded for {language.name}', 'language_id': language_id})
        else:
            ad.final_asset.save(safe_name, file, save=True)
            ad.save()
            return Response({'message': 'Final asset uploaded successfully'})

    @action(detail=True, methods=['get'])
    def language_assets_list(self, request, pk=None):
        ad = self.get_object()
        assets = ad.language_assets.all()
        serializer = AdLanguageAssetSerializer(assets, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def generate_video(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        if ad.status != 'approved':
            return Response({'error': 'Ad must be approved first'}, status=400)

        language_id = request.data.get('language_id')
        if not language_id:
            return Response({'error': 'language_id is required'}, status=400)

        try:
            language = Language.objects.get(id=language_id)
        except Language.DoesNotExist:
            return Response({'error': 'Invalid language_id'}, status=400)

        asset_obj, created = AdLanguageAsset.objects.get_or_create(
            ad=ad, language=language,
            defaults={'status': 'pending', 'prompt': ''}
        )

        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            prompt = ad.description or ad.text_content or ad.title
        if not prompt:
            return Response({'error': 'No prompt provided and no text content on ad'}, status=400)

        if prompt != asset_obj.prompt:
            asset_obj.prompt = prompt
        asset_obj.status = 'generating'
        asset_obj.error = ''
        asset_obj.save()

        manager_api_key = _get_manager_api_key(request.user)

        def _generate(asset):
            nonlocal manager_api_key
            try:
                video_file, _ = generate_video_from_text(asset.prompt, api_key=manager_api_key)
                asset.asset.save(video_file.name, video_file, save=True)
                asset.status = 'completed'
                asset.error = ''
                asset.save()
            except Exception as e:
                err_msg = str(e)
                print(f'Veo generation failed for ad {asset.ad_id} language {asset.language_id}: {err_msg}')
                AdLanguageAsset.objects.filter(id=asset.id).update(status='failed', error=err_msg)

        thread = threading.Thread(target=_generate, args=(asset_obj,))
        thread.start()

        return Response({'message': f'Video generation started for {language.name}', 'language_id': language_id})

    @action(detail=True, methods=['patch'])
    def update_language_asset(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        asset_id = request.data.get('id')
        if not asset_id:
            return Response({'error': 'Asset id is required'}, status=400)
        try:
            asset_obj = ad.language_assets.get(id=asset_id)
        except AdLanguageAsset.DoesNotExist:
            return Response({'error': 'Asset not found'}, status=404)

        if 'prompt' in request.data:
            asset_obj.prompt = request.data['prompt']
            asset_obj.save()
        return Response(AdLanguageAssetSerializer(asset_obj).data)

    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)

        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'CSV file required'}, status=400)

        try:
            content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
        except Exception as e:
            return Response({'error': f'Invalid CSV: {str(e)}'}, status=400)

        results = {'created': 0, 'errors': []}
        for row in reader:
            title = row.get('title', '').strip()
            if not title:
                results['errors'].append({'row': reader.line_num, 'error': 'title is required'})
                continue

            description = row.get('description', '').strip()
            target_area_ids = []
            state = row.get('state', '').strip()
            city = row.get('city', '').strip()
            locality = row.get('locality', '').strip()
            if state and city and locality:
                ids = list(TargetArea.objects.filter(
                    state__iexact=state, city__iexact=city, locality__iexact=locality
                ).values_list('id', flat=True))
                target_area_ids = ids

            audience_name = row.get('audience_profile', '').strip()
            target_audience_ids = []
            if audience_name:
                ids = list(TargetAudience.objects.filter(
                    profile__iexact=audience_name
                ).values_list('id', flat=True))
                target_audience_ids = ids

            language_name = row.get('language', '').strip()
            language_ids = []
            if language_name:
                ids = list(Language.objects.filter(
                    name__iexact=language_name
                ).values_list('id', flat=True))
                language_ids = ids

            scheduled_start = row.get('scheduled_start', '').strip() or None
            scheduled_end = row.get('scheduled_end', '').strip() or None

            ad = Ad.objects.create(
                client=request.user,
                title=title,
                description=description,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                status='pending_approval',
            )
            if target_area_ids:
                ad.target_areas.set(target_area_ids)
            if target_audience_ids:
                ad.target_audiences.set(target_audience_ids)
            if language_ids:
                ad.languages.set(language_ids)
            results['created'] += 1

        return Response(results, status=201)

    @action(detail=True, methods=['post'])
    def push_to_app(self, request, pk=None):
        ad = self.get_object()
        if not getattr(request.user, 'is_staff', False) and ad.client != request.user:
            return Response({'error': 'Not authorized'}, status=403)
        if ad.status != 'approved':
            return Response({'error': 'Only approved ads can be pushed'}, status=400)

        app_ids = request.data.get('app_ids') or [request.data.get('app_id')]
        if not app_ids or not any(app_ids):
            return Response({'error': 'app_ids (list) or app_id is required'}, status=400)

        if not isinstance(app_ids, list):
            app_ids = [app_ids]

        apps = DeveloperApp.objects.filter(id__in=app_ids, is_active=True)
        if not apps.exists():
            return Response({'error': 'No valid developer apps found'}, status=404)

        results = []
        for app in apps:
            push, created = AdDeveloperPush.objects.get_or_create(ad=ad, app=app)
            results.append({
                'app_id': app.id,
                'app_name': app.app_name,
                'push_id': push.id,
                'created': created,
            })
        return Response({'message': f'Ad pushed to {len(results)} app(s)', 'results': results})

    @action(detail=True, methods=['get'])
    def pushed_apps(self, request, pk=None):
        ad = self.get_object()
        pushes = ad.developer_pushes.select_related('app__developer')
        data = [
            {
                'push_id': p.id,
                'app_id': p.app.id,
                'app_name': p.app.app_name,
                'app_type': p.app.app_type,
                'app_url': p.app.app_url,
                'company': p.app.developer.company_name,
                'rating': p.app.rating,
                'pushed_at': p.pushed_at,
            }
            for p in pushes
        ]
        return Response(data)


    @action(detail=False, methods=['post'])
    def generate_image(self, request):
        """Generate an image from a text prompt using Google's Imagen API."""
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)

        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            return Response({'error': 'prompt is required'}, status=400)

        aspect_ratio = request.data.get('aspect_ratio', '1:1')
        model_id = request.data.get('model', 'gemini-3.1-flash-image')
        input_image = request.data.get('input_image')

        # Validate model
        model_info = get_model_info(model_id)
        if not model_info:
            return Response({'error': f'Unknown model: {model_id}'}, status=400)

        try:
            api_key = _get_manager_api_key(request.user)
            api_type = model_info.get('api_type', 'predictLongRunning')
            if api_type == 'interactions':
                image_file, resp_headers = generate_nano_banana_image(prompt, aspect_ratio=aspect_ratio, model_name=model_id, api_key=api_key, input_image=input_image)
            elif api_type == 'generateContent':
                image_file, resp_headers = generate_gemini_image(prompt, aspect_ratio=aspect_ratio, model_name=model_id, api_key=api_key, input_image=input_image)
            else:
                image_file, resp_headers = generate_image_from_text(prompt, aspect_ratio=aspect_ratio, model_name=model_id, api_key=api_key)

            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            path = default_storage.save(f'creative_images/{image_file.name}', ContentFile(image_file.read()))
            url = request.build_absolute_uri(default_storage.url(path))

            gm = GeneratedMedia.objects.create(
                user=request.user,
                media_type='image',
                file=path,
                prompt=prompt,
                model_used=model_id,
                aspect_ratio=aspect_ratio,
            )

            return Response({
                'url': url,
                'path': path,
                'prompt': prompt,
                'aspect_ratio': aspect_ratio,
                'model_used': model_id,
                'google_api_quota': get_remaining_quota(),
                'generated_media_id': gm.id,
            })
        except QuotaExceededError as e:
            quota = get_remaining_quota()
            return Response({
                'error': str(e),
                'quota': quota,
                'google_api_quota': quota,
            }, status=429)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'])
    def generate_video_clip(self, request):
        """Generate a video clip from a text prompt using Google's Veo API.
        Optionally accepts an input_image (base64 PNG) for image-conditioned generation."""
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)

        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            return Response({'error': 'prompt is required'}, status=400)

        duration = int(request.data.get('duration_seconds', 8))
        duration = min((v for v in (4, 6, 8) if v >= duration), default=8)
        target_duration = int(request.data.get('target_duration_seconds', 0)) or None
        aspect_ratio = request.data.get('aspect_ratio', '16:9')
        # Veo only supports 16:9 and 9:16 — clamp anything else
        if aspect_ratio not in ('16:9', '9:16'):
            aspect_ratio = '16:9'
        model_id = request.data.get('model', 'veo-3.1-generate-preview')
        input_image = request.data.get('input_image', '').strip() or None
        last_frame = request.data.get('last_frame', '').strip() or None

        # Validate model
        model_info = get_model_info(model_id)
        if not model_info:
            return Response({'error': f'Unknown model: {model_id}'}, status=400)

        try:
            api_key = _get_manager_api_key(request.user)
            video_file, resp_headers = generate_video_from_text(prompt, duration_seconds=duration, aspect_ratio=aspect_ratio, model_name=model_id, api_key=api_key, target_duration_seconds=target_duration, input_image_base64=input_image, last_frame_base64=last_frame)

            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            path = default_storage.save(f'creative_videos/{video_file.name}', ContentFile(video_file.read()))
            url = request.build_absolute_uri(default_storage.url(path))

            gm = GeneratedMedia.objects.create(
                user=request.user,
                media_type='video',
                file=path,
                prompt=prompt,
                model_used=model_id,
                duration_seconds=target_duration or duration,
                aspect_ratio=aspect_ratio,
            )

            return Response({
                'url': url,
                'path': path,
                'prompt': prompt,
                'duration_seconds': duration,
                'target_duration_seconds': target_duration,
                'aspect_ratio': aspect_ratio,
                'model_used': model_id,
                'google_api_quota': get_remaining_quota(),
                'generated_media_id': gm.id,
            })
        except QuotaExceededError as e:
            quota = get_remaining_quota()
            return Response({
                'error': str(e),
                'quota': quota,
                'google_api_quota': quota,
            }, status=429)
        except ValueError as e:
            # Invalid input_image format — client error
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            error_msg = str(e)
            # Surface Veo 400 (bad request) as 400, not 500
            if 'Veo API error 400' in error_msg:
                return Response({'error': error_msg}, status=400)
            return Response({'error': error_msg}, status=500)

    @action(detail=False, methods=['post'])
    def proxy_image(self, request):
        """Fetch an image server-side and return as base64 data URL.
        Bypasses CORS restrictions on cross-origin images (e.g. S3)."""
        image_url = (request.data.get('url') or '').strip()
        if not image_url:
            return Response({'error': 'url is required'}, status=400)

        parsed = urlparse(image_url)
        if parsed.scheme not in ('http', 'https'):
            return Response({'error': 'Only http/https URLs are allowed'}, status=400)

        hostname = parsed.hostname or ''
        if hostname in ('localhost', '127.0.0.1', '::1', '0.0.0.0') or hostname.endswith('.local'):
            return Response({'error': 'Internal URLs are not allowed'}, status=400)

        import ipaddress
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return Response({'error': 'Private network URLs are not allowed'}, status=400)
        except ValueError:
            pass

        try:
            resp = http_requests.get(image_url, timeout=30, stream=True)
            if resp.status_code != 200:
                return Response({'error': f'Failed to fetch image: {resp.status_code}'}, status=400)

            content_type = resp.headers.get('Content-Type', 'image/png')
            mime_map = {
                'image/jpg': 'image/jpeg',
                'image/jpeg': 'image/jpeg',
                'image/png': 'image/png',
                'image/webp': 'image/webp',
                'image/gif': 'image/gif',
            }
            mime_type = mime_map.get(content_type.split(';')[0].strip().lower(), 'image/png')

            image_bytes = resp.content
            if len(image_bytes) > 15 * 1024 * 1024:
                return Response({'error': 'Image too large (max 11MB)'}, status=400)

            b64 = base64.b64encode(image_bytes).decode('ascii')
            data_url = f'data:{mime_type};base64,{b64}'
            return Response({'data_url': data_url, 'mime_type': mime_type})
        except http_requests.Timeout:
            return Response({'error': 'Image fetch timed out'}, status=400)
        except Exception as e:
            return Response({'error': f'Failed to fetch image: {str(e)}'}, status=400)

    @action(detail=False, methods=['delete'])
    def delete_asset(self, request):
        """Delete a generated asset (GeneratedMedia + linked session events).
        Accepts: { "media_id": <int> } or { "event_id": <int> } or both."""
        media_id = request.data.get('media_id')
        event_id = request.data.get('event_id')

        if not media_id and not event_id:
            return Response({'error': 'media_id or event_id is required'}, status=400)

        deleted_media = False
        deleted_events = 0
        media = None
        event = None

        if media_id:
            try:
                media = GeneratedMedia.objects.get(id=media_id, user=request.user)
            except GeneratedMedia.DoesNotExist:
                pass

        if event_id:
            try:
                event = CreativeSessionEvent.objects.get(id=event_id, session__user=request.user)
            except CreativeSessionEvent.DoesNotExist:
                pass

        if not media and event and event.generated_media_id:
            try:
                media = GeneratedMedia.objects.get(id=event.generated_media_id, user=request.user)
            except GeneratedMedia.DoesNotExist:
                pass

        if media:
            linked_events = CreativeSessionEvent.objects.filter(generated_media=media)
            deleted_events = linked_events.count()
            linked_events.delete()
            if media.file:
                try:
                    from django.core.files.storage import default_storage
                    default_storage.delete(media.file.name)
                except Exception:
                    pass
            media.delete()
            deleted_media = True
        elif event:
            event.delete()
            deleted_events = 1

        return Response({'deleted_media': deleted_media, 'deleted_events': deleted_events})

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def media_proxy(self, request):
        """Proxy a remote media URL (e.g. S3) with CORS headers.
        Usage: GET /api/ads/media_proxy/?url=<encoded_url>"""
        from django.http import StreamingHttpResponse
        import ipaddress as _ipaddress

        image_url = request.query_params.get('url', '').strip()
        if not image_url:
            return Response({'error': 'url query param is required'}, status=400)

        parsed = urlparse(image_url)
        if parsed.scheme not in ('http', 'https'):
            return Response({'error': 'Only http/https URLs are allowed'}, status=400)

        hostname = parsed.hostname or ''
        if hostname in ('localhost', '127.0.0.1', '::1', '0.0.0.0') or hostname.endswith('.local'):
            return Response({'error': 'Internal URLs are not allowed'}, status=400)
        try:
            ip = _ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return Response({'error': 'Private network URLs are not allowed'}, status=400)
        except ValueError:
            pass

        try:
            resp = http_requests.get(image_url, timeout=30, stream=True)
            if resp.status_code != 200:
                return Response({'error': f'Upstream error: {resp.status_code}'}, status=502)

            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            content_length = resp.headers.get('Content-Length')

            django_resp = StreamingHttpResponse(
                resp.iter_content(chunk_size=64 * 1024),
                status=200,
                content_type=content_type,
            )
            django_resp['Access-Control-Allow-Origin'] = '*'
            django_resp['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
            django_resp['Access-Control-Allow-Headers'] = '*'
            if content_length:
                django_resp['Content-Length'] = content_length
            cache_etag = resp.headers.get('ETag')
            if cache_etag:
                django_resp['ETag'] = cache_etag
            django_resp['Cache-Control'] = 'public, max-age=86400'
            return django_resp
        except http_requests.Timeout:
            return Response({'error': 'Upstream timeout'}, status=502)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'])
    def create_creative(self, request):
        """Create an ad directly as a manager (bypasses client submission)."""
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)

        title = request.data.get('title', '').strip()
        if not title:
            return Response({'error': 'title is required'}, status=400)

        description = request.data.get('description', '').strip()
        image_url = request.data.get('image_url', '').strip()
        video_url = request.data.get('video_url', '').strip()
        target_area_ids = request.data.get('target_area_ids', [])
        target_audience_ids = request.data.get('target_audience_ids', [])
        language_ids = request.data.get('language_ids', [])
        scheduled_start = request.data.get('scheduled_start', None)
        scheduled_end = request.data.get('scheduled_end', None)

        ad = Ad.objects.create(
            client=request.user,
            title=title,
            description=description,
            status='approved',
            scheduled_start=scheduled_start or None,
            scheduled_end=scheduled_end or None,
        )

        if target_area_ids:
            ad.target_areas.set(TargetArea.objects.filter(id__in=target_area_ids))
        if target_audience_ids:
            ad.target_audiences.set(TargetAudience.objects.filter(id__in=target_audience_ids))
        if language_ids:
            ad.languages.set(Language.objects.filter(id__in=language_ids))

        # Handle image upload
        if 'image_file' in request.FILES:
            ad.asset = request.FILES['image_file']
        elif image_url:
            from django.core.files.storage import default_storage
            from django.core.files import File
            local_path = image_url.replace(request.build_absolute_uri('/'), '')
            if default_storage.exists(local_path):
                f = default_storage.open(local_path)
                ad.asset.save(os.path.basename(local_path), File(f), save=False)

        # Handle video
        if 'video_file' in request.FILES:
            ad.final_asset = request.FILES['video_file']
        elif video_url:
            from django.core.files.storage import default_storage
            from django.core.files import File
            local_path = video_url.replace(request.build_absolute_uri('/'), '')
            if default_storage.exists(local_path):
                f = default_storage.open(local_path)
                ad.final_asset.save(os.path.basename(local_path), File(f), save=False)

        ad.save()

        serializer = AdDetailSerializer(ad, context={'request': request})
        return Response(serializer.data, status=201)


class DeveloperAppViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DeveloperAppSerializer

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_staff', False):
            return DeveloperApp.objects.all()
        try:
            from accounts.models import Developer
            dev = Developer.objects.get(user=user, is_active=True)
            return DeveloperApp.objects.filter(developer=dev)
        except (Developer.DoesNotExist, ValueError):
            return DeveloperApp.objects.filter(is_active=True)

    def perform_create(self, serializer):
        from accounts.models import Developer
        dev = Developer.objects.get(user=self.request.user, is_active=True)
        serializer.save(developer=dev)


class DeveloperAdViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DeveloperAdListSerializer

    def get_queryset(self):
        return Ad.objects.filter(status='approved').distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        for i, ad in enumerate(queryset):
            pushes = ad.developer_pushes.select_related('app').all()
            data[i]['pushed_apps'] = [
                {
                    'app_name': p.app.app_name,
                    'app_type': p.app.app_type,
                    'app_url': p.app.app_url,
                }
                for p in pushes
            ]
        return Response(data)

    @action(detail=True, methods=['get'])
    def details(self, request, pk=None):
        try:
            ad = self.get_queryset().get(pk=pk)
        except Ad.DoesNotExist:
            return Response({'error': 'Ad not found'}, status=404)
        serializer = AdDetailSerializer(ad, context={'request': request})
        data = serializer.data
        pushes = ad.developer_pushes.select_related('app__developer')
        data['pushed_apps'] = [
            {
                'push_id': p.id,
                'app_id': p.app.id,
                'app_name': p.app.app_name,
                'app_type': p.app.app_type,
                'app_url': p.app.app_url,
                'company': p.app.developer.company_name,
                'pushed_at': p.pushed_at,
            }
            for p in pushes
        ]
        return Response(data)


@api_view(['POST'])
@permission_classes([AllowAny])
def enhance_prompt(request):
    """
    Enhance a generation prompt using OpenRouter AI.
    Preserves the user's language and adds rich detail.
    """
    prompt = (request.data.get('prompt') or '').strip()
    if not prompt:
        return Response({'error': 'prompt is required'}, status=400)

    media_type = request.data.get('media_type', 'image')
    width = request.data.get('width', 1024)
    height = request.data.get('height', 1024)
    edit_mode = request.data.get('edit_mode', False)

    try:
        result = enhance_prompt_service(prompt, media_type=media_type, width=width, height=height, edit_mode=edit_mode)
        return Response({
            'original': prompt,
            'enhanced': result['enhanced'],
            'negative_prompt': result['negative_prompt'],
            'media_type': media_type,
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Enhance prompt error: {e}')
        return Response({'error': str(e)}, status=502)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_target_areas(request):
    if request.method == 'GET':
        areas = TargetArea.objects.all()
        return Response(TargetAreaSerializer(areas, many=True).data)

    serializer = TargetAreaSerializer(data=request.data, many=isinstance(request.data, list))
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([AllowAny])
def public_ads(request):
    api_key = request.GET.get('api_key') or request.headers.get('X-API-Key')
    if not api_key:
        return Response({'error': 'API key required via ?api_key= or X-API-Key header'}, status=401)

    try:
        app = DeveloperApp.objects.get(api_key=api_key, is_active=True)
    except DeveloperApp.DoesNotExist:
        try:
            from accounts.models import Developer
            dev = Developer.objects.get(api_key=api_key, is_active=True)
            apps = DeveloperApp.objects.filter(developer=dev, is_active=True)
            ad_ids = AdDeveloperPush.objects.filter(app__in=apps).values_list('ad_id', flat=True)
            ads = Ad.objects.filter(id__in=ad_ids, status='approved')
            serializer = PublicAdSerializer(ads, many=True, context={'request': request})
            return Response({
                'developer': dev.company_name,
                'total': ads.count(),
                'ads': serializer.data,
            })
        except Developer.DoesNotExist:
            return Response({'error': 'Invalid API key'}, status=401)

    ad_ids = AdDeveloperPush.objects.filter(app=app).values_list('ad_id', flat=True)
    ads = Ad.objects.filter(id__in=ad_ids, status='approved')
    serializer = PublicAdSerializer(ads, many=True, context={'request': request})
    return Response({
        'app': app.app_name,
        'total': ads.count(),
        'ads': serializer.data,
    })


class VideoFeedbackViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = VideoFeedbackSerializer

    def get_queryset(self):
        return VideoFeedback.objects.filter(ad_id=self.kwargs.get('ad_pk')).order_by('created_at')

    def perform_create(self, serializer):
        user = self.request.user
        name = getattr(user, 'name', '') or getattr(user, 'username', '')
        role = 'admin' if getattr(user, 'is_staff', False) else 'client'
        kwargs = {'user_name': name, 'created_by': role, 'ad_id': self.kwargs.get('ad_pk')}
        lang_asset_id = self.request.data.get('language_asset_id')
        if lang_asset_id:
            try:
                from .models import AdLanguageAsset
                asset = AdLanguageAsset.objects.get(id=lang_asset_id, ad_id=self.kwargs.get('ad_pk'))
                kwargs['language_asset'] = asset
            except AdLanguageAsset.DoesNotExist:
                pass
        serializer.save(**kwargs)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def creative_sessions_list(request):
    if request.method == 'GET':
        sessions = CreativeSession.objects.filter(user=request.user)
        serializer = CreativeSessionListSerializer(sessions, many=True, context={'request': request})
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = CreativeSessionCreateSerializer(data=request.data)
        if serializer.is_valid():
            session = serializer.save(user=request.user)
            detail_serializer = CreativeSessionDetailSerializer(session, context={'request': request})
            return Response(detail_serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def creative_session_detail(request, pk):
    try:
        session = CreativeSession.objects.get(pk=pk, user=request.user)
    except CreativeSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=404)

    if request.method == 'GET':
        serializer = CreativeSessionDetailSerializer(session, context={'request': request})
        return Response(serializer.data)
    elif request.method == 'PATCH':
        serializer = CreativeSessionCreateSerializer(session, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            detail_serializer = CreativeSessionDetailSerializer(session, context={'request': request})
            return Response(detail_serializer.data)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        session.delete()
        return Response(status=204)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def creative_session_add_event(request, pk):
    try:
        session = CreativeSession.objects.get(pk=pk, user=request.user)
    except CreativeSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=404)

    event_type = request.data.get('event_type')
    if event_type not in dict(CreativeSessionEvent.EVENT_TYPES):
        return Response({'error': f'Invalid event type. Must be one of: {", ".join(dict(CreativeSessionEvent.EVENT_TYPES).keys())}'}, status=400)

    generated_media_id = request.data.get('generated_media_id')
    generated_media = None
    if generated_media_id:
        try:
            generated_media = GeneratedMedia.objects.get(id=generated_media_id, user=request.user)
        except GeneratedMedia.DoesNotExist:
            return Response({'error': 'Generated media not found'}, status=404)

    event = CreativeSessionEvent.objects.create(
        session=session,
        event_type=event_type,
        prompt=request.data.get('prompt', ''),
        settings=request.data.get('settings', {}),
        generated_media=generated_media,
        file=request.data.get('file', ''),
    )

    # Update session title from first generate event
    if event_type == 'generate' and not session.title:
        title = (request.data.get('prompt', '') or '')[:80]
        session.title = title or f'Session {session.id}'
        session.save(update_fields=['title'])

    serializer = CreativeSessionEventSerializer(event, context={'request': request})
    return Response(serializer.data, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def log_credit_usage(request):
    """Log credit consumption for a generation."""
    serializer = CreditUsageLogSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(user=request.user)
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def monthly_credit_stats(request):
    """Get this month's credit usage stats for the current user."""
    now = timezone.now()
    try:
        year = int(request.query_params.get('year', now.year))
    except (ValueError, TypeError):
        year = now.year
    try:
        month = int(request.query_params.get('month', now.month))
    except (ValueError, TypeError):
        month = now.month

    logs = CreditUsageLog.objects.filter(
        user=request.user,
        created_at__year=year,
        created_at__month=month,
    )

    total = logs.aggregate(
        total_credits=Sum('credit_cost') or 0,
        total_generations=Count('id') or 0,
    )
    image_stats = logs.filter(media_type='image').aggregate(
        image_credits=Sum('credit_cost') or 0,
        image_generations=Count('id') or 0,
    )
    video_stats = logs.filter(media_type='video').aggregate(
        video_credits=Sum('credit_cost') or 0,
        video_generations=Count('id') or 0,
    )

    data = {
        'total_credits': total['total_credits'] or 0,
        'total_generations': total['total_generations'] or 0,
        'image_credits': image_stats['image_credits'] or 0,
        'image_generations': image_stats['image_generations'] or 0,
        'video_credits': video_stats['video_credits'] or 0,
        'video_generations': video_stats['video_generations'] or 0,
        'year': year,
        'month': month,
    }
    serializer = MonthlyCreditStatsSerializer(data)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_tracking_logs(request):
    """Return API usage logs categorized by billing status for the tracking page.
    Supports pagination via page and page_size query params."""
    logs = ApiUsageLog.objects.all()

    # Filtering
    model = request.query_params.get('model', '')
    status_filter = request.query_params.get('status', 'all')

    if model:
        logs = logs.filter(model_id__icontains=model)
    if status_filter == 'billed_success':
        logs = logs.filter(model_id__contains='_output:') | logs.filter(model_id__contains='_gen:', success=True)
        logs = logs.exclude(model_id__contains='_billed_fail').exclude(model_id__contains='_poll').exclude(model_id__contains='_fail:')
    elif status_filter == 'billed_failed':
        logs = logs.filter(model_id__contains='_billed_fail')
    elif status_filter == 'free':
        logs = logs.filter(success=False).exclude(model_id__contains='_billed_fail')

    # Total count before pagination
    total = logs.count()

    # Pagination
    try:
        page = int(request.query_params.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = int(request.query_params.get('page_size', 10))
    except (ValueError, TypeError):
        page_size = 10
    page_size = min(max(page_size, 1), 100)  # Clamp between 1 and 100
    offset = (page - 1) * page_size
    logs_page = logs[offset:offset + page_size]

    serializer = ApiUsageLogSerializer(logs_page, many=True)

    # Summary counts (always based on filtered logs, not paginated)
    all_logs = ApiUsageLog.objects.all()
    summary = {
        'total': all_logs.count(),
        'billed_success': (all_logs.filter(model_id__contains='_output:') | all_logs.filter(model_id__contains='_gen:', success=True)).exclude(model_id__contains='_billed_fail').exclude(model_id__contains='_poll').exclude(model_id__contains='_fail:').count(),
        'billed_failed': all_logs.filter(model_id__contains='_billed_fail').count(),
        'free_polling': all_logs.filter(model_id__contains='_poll:').count(),
        'free_transient': all_logs.filter(model_id__contains='_gen:', success=False).count(),
    }

    return Response({
        'logs': serializer.data,
        'summary': summary,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_media(request):
    """Upload an arbitrary media file and return its URL."""
    file = request.FILES.get('file')
    if not file:
        return Response({'error': 'No file provided'}, status=400)

    import uuid
    from django.core.files.storage import default_storage
    ext = file.name.split('.')[-1] if '.' in file.name else 'webm'
    filename = f'uploads/{uuid.uuid4().hex}.{ext}'
    saved_path = default_storage.save(filename, file)

    url = request.build_absolute_uri(default_storage.url(saved_path))
    return Response({'url': url}, status=201)
