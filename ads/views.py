import csv
import io
import threading
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.response import Response
from .models import TargetArea, TargetAudience, Language, Ad, AdIteration, AdLanguageAsset, DeveloperApp, AdDeveloperPush
from .serializers import (
    TargetAreaSerializer, TargetAudienceSerializer, LanguageSerializer,
    AdListSerializer, AdDetailSerializer, AdStatusSerializer,
    AdIterationSerializer, AdLanguageAssetSerializer,
    DeveloperAppSerializer, AdDeveloperPushSerializer, PublicAdSerializer,
    DeveloperAdListSerializer
)
from .services.veo import generate_video_from_text
from .services.imagen import generate_image_from_text
from .services.openrouter import enhance_prompt as enhance_prompt_service


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

        def _generate(asset):
            try:
                video_file = generate_video_from_text(asset.prompt)
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
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        if ad.status != 'approved':
            return Response({'error': 'Only approved ads can be pushed'}, status=400)

        app_id = request.data.get('app_id')
        if not app_id:
            return Response({'error': 'app_id is required'}, status=400)

        try:
            app = DeveloperApp.objects.get(id=app_id, is_active=True)
        except DeveloperApp.DoesNotExist:
            return Response({'error': 'Developer app not found'}, status=404)

        push, created = AdDeveloperPush.objects.get_or_create(ad=ad, app=app)
        return Response({'message': f'Ad pushed to {app.app_name}', 'push_id': push.id, 'created': created})

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
                'company': p.app.developer.company_name,
                'pushed_at': p.pushed_at,
            }
            for p in pushes
        ]
        return Response(data)


    @action(detail=False, methods=['post'])
    def generate_image(self, request):
        """Generate an image from a text prompt using Imagen API."""
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)

        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            return Response({'error': 'prompt is required'}, status=400)

        aspect_ratio = request.data.get('aspect_ratio', '1:1')

        try:
            image_file = generate_image_from_text(prompt, aspect_ratio=aspect_ratio)
            # Save as a temporary creative asset
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            path = default_storage.save(f'creative_images/{image_file.name}', ContentFile(image_file.read()))
            url = request.build_absolute_uri(default_storage.url(path))
            return Response({
                'url': url,
                'path': path,
                'prompt': prompt,
                'aspect_ratio': aspect_ratio,
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'])
    def generate_video_clip(self, request):
        """Generate a video clip from a text prompt using Veo API (standalone)."""
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)

        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            return Response({'error': 'prompt is required'}, status=400)

        duration = request.data.get('duration_seconds', 8)
        aspect_ratio = request.data.get('aspect_ratio', '16:9')

        try:
            video_file = generate_video_from_text(prompt, duration_seconds=duration, aspect_ratio=aspect_ratio)
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            path = default_storage.save(f'creative_videos/{video_file.name}', ContentFile(video_file.read()))
            url = request.build_absolute_uri(default_storage.url(path))
            return Response({
                'url': url,
                'path': path,
                'prompt': prompt,
                'duration_seconds': duration,
                'aspect_ratio': aspect_ratio,
            })
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
            # Try to copy from creative_images path
            import os
            from django.conf import settings
            local_path = image_url.replace(request.build_absolute_uri('/'), '')
            full_path = os.path.join(settings.MEDIA_ROOT, local_path) if hasattr(settings, 'MEDIA_ROOT') else None
            if full_path and os.path.exists(full_path):
                from django.core.files import File
                with open(full_path, 'rb') as f:
                    ad.asset.save(os.path.basename(full_path), File(f), save=False)

        # Handle video
        if 'video_file' in request.FILES:
            ad.final_asset = request.FILES['video_file']
        elif video_url:
            import os
            from django.conf import settings
            local_path = video_url.replace(request.build_absolute_uri('/'), '')
            full_path = os.path.join(settings.MEDIA_ROOT, local_path) if hasattr(settings, 'MEDIA_ROOT') else None
            if full_path and os.path.exists(full_path):
                from django.core.files import File
                with open(full_path, 'rb') as f:
                    ad.final_asset.save(os.path.basename(full_path), File(f), save=False)

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
        except Developer.DoesNotExist:
            return DeveloperApp.objects.none()
        return DeveloperApp.objects.filter(developer=dev)

    def perform_create(self, serializer):
        from accounts.models import Developer
        dev = Developer.objects.get(user=self.request.user, is_active=True)
        serializer.save(developer=dev)


class DeveloperAdViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DeveloperAdListSerializer

    def get_queryset(self):
        user = self.request.user
        try:
            from accounts.models import Developer
            dev = Developer.objects.get(user=user, is_active=True)
        except Developer.DoesNotExist:
            return Ad.objects.none()
        return Ad.objects.filter(
            status='approved',
            developer_pushes__app__developer=dev
        ).distinct()

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
    prompt = request.data.get('prompt', '').strip()
    if not prompt:
        return Response({'error': 'prompt is required'}, status=400)

    media_type = request.data.get('media_type', 'image')
    width = request.data.get('width', 1024)
    height = request.data.get('height', 1024)

    try:
        result = enhance_prompt_service(prompt, media_type=media_type, width=width, height=height)
        return Response({
            'original': prompt,
            'enhanced': result['enhanced'],
            'negative_prompt': result['negative_prompt'],
            'media_type': media_type,
        })
    except Exception as e:
        return Response({'error': str(e)}, status=500)


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
