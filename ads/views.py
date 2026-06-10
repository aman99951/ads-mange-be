import threading
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from .models import TargetArea, TargetAudience, Ad, AdIteration
from .serializers import (
    TargetAreaSerializer, TargetAudienceSerializer,
    AdListSerializer, AdDetailSerializer, AdStatusSerializer,
    AdIterationSerializer
)
from .services.veo import generate_video_from_text


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


class AdViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return AdListSerializer
        if self.action in ['approve', 'reject']:
            return AdStatusSerializer
        return AdDetailSerializer

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_staff', False):
            return Ad.objects.all()
        return Ad.objects.filter(client=user)

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
        if not ad.final_asset:
            return Response({'error': 'No final asset available'}, status=404)
        return Response({'url': request.build_absolute_uri(ad.final_asset.url)})

    @action(detail=True, methods=['post'])
    def generate_video(self, request, pk=None):
        if not getattr(request.user, 'is_staff', False):
            return Response({'error': 'Admin only'}, status=403)
        ad = self.get_object()
        if ad.status != 'approved':
            return Response({'error': 'Ad must be approved first'}, status=400)
        prompt = ad.text_content or ad.description or ad.title
        if not prompt:
            return Response({'error': 'No text content to generate video from'}, status=400)

        def _generate(ad_obj, prompt_text):
            try:
                video_file = generate_video_from_text(prompt_text)
                ad_obj.final_asset.save(video_file.name, video_file, save=True)
                ad_obj.generation_error = ''
                ad_obj.save()
            except Exception as e:
                err_msg = str(e)
                print(f'Veo generation failed for ad {ad_obj.id}: {err_msg}')
                Ad.objects.filter(id=ad_obj.id).update(generation_error=err_msg)

        thread = threading.Thread(target=_generate, args=(ad, prompt))
        thread.start()

        return Response({'message': 'Video generation started', 'status': ad.status})


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
