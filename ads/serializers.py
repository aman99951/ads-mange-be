from rest_framework import serializers
from .models import TargetArea, TargetAudience, Language, Ad, AdIteration, AdLanguageAsset, DeveloperApp, AdDeveloperPush, GeneratedMedia, VideoFeedback, CreativeSession, CreativeSessionEvent


class TargetAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetArea
        fields = '__all__'


class TargetAudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetAudience
        fields = '__all__'


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = '__all__'


class AdLanguageAssetSerializer(serializers.ModelSerializer):
    language_name = serializers.CharField(source='language.name', read_only=True)

    class Meta:
        model = AdLanguageAsset
        fields = '__all__'
        read_only_fields = ['ad', 'asset', 'status', 'error', 'created_at', 'updated_at']


class AdIterationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdIteration
        fields = '__all__'
        read_only_fields = ['created_at', 'ad', 'created_by']


class VideoFeedbackSerializer(serializers.ModelSerializer):
    language_name = serializers.CharField(source='language_asset.language.name', read_only=True, default='')

    class Meta:
        model = VideoFeedback
        fields = ['id', 'ad', 'language_asset', 'language_name', 'user_name', 'created_by', 'comment', 'timestamp_seconds', 'created_at']
        read_only_fields = ['ad', 'language_name', 'user_name', 'created_by', 'created_at']


class AdListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_mobile = serializers.CharField(source='client.mobile', read_only=True)

    class Meta:
        model = Ad
        fields = [
            'id', 'title', 'status', 'client_name', 'client_mobile',
            'content_type', 'content_size',
            'scheduled_start', 'scheduled_end',
            'created_at', 'updated_at'
        ]


class RevisionRequestSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    latest_feedback = serializers.SerializerMethodField()

    class Meta:
        model = Ad
        fields = [
            'id', 'title', 'status', 'client_name',
            'created_at', 'updated_at', 'latest_feedback'
        ]

    def get_latest_feedback(self, obj):
        iteration = obj.iterations.order_by('-created_at').first()
        if iteration:
            return {
                'id': iteration.id,
                'feedback': iteration.feedback,
                'created_by': iteration.created_by,
                'created_at': iteration.created_at,
            }
        return None


class AdDetailSerializer(serializers.ModelSerializer):
    target_areas = TargetAreaSerializer(many=True, read_only=True)
    target_audiences = TargetAudienceSerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    language_assets = AdLanguageAssetSerializer(many=True, read_only=True)
    target_area_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    target_audience_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    language_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    iterations = AdIterationSerializer(many=True, read_only=True)
    video_feedback = VideoFeedbackSerializer(many=True, read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_mobile = serializers.CharField(source='client.mobile', read_only=True)

    class Meta:
        model = Ad
        fields = [
            'id', 'client', 'title', 'description', 'target_areas',
            'target_audiences', 'languages', 'language_assets',
            'target_area_ids', 'target_audience_ids', 'language_ids',
            'asset', 'text_content', 'status', 'admin_feedback', 'final_asset',
            'generation_error', 'content_type', 'content_size',
            'client_name', 'client_mobile',
            'scheduled_start', 'scheduled_end',
            'created_at', 'updated_at', 'iterations', 'video_feedback'
        ]
        read_only_fields = ['client', 'status', 'admin_feedback', 'final_asset', 'generation_error', 'created_at', 'updated_at', 'iterations', 'video_feedback']

    def create(self, validated_data):
        target_area_ids = validated_data.pop('target_area_ids', [])
        target_audience_ids = validated_data.pop('target_audience_ids', [])
        language_ids = validated_data.pop('language_ids', [])
        ad = Ad.objects.create(**validated_data)
        if target_area_ids:
            ad.target_areas.set(TargetArea.objects.filter(id__in=target_area_ids))
        if target_audience_ids:
            ad.target_audiences.set(TargetAudience.objects.filter(id__in=target_audience_ids))
        if language_ids:
            ad.languages.set(Language.objects.filter(id__in=language_ids))
        return ad


class AdStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ad
        fields = ['status', 'admin_feedback', 'final_asset', 'generation_error']


class DeveloperAppSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source='developer.company_name', read_only=True)

    class Meta:
        model = DeveloperApp
        fields = '__all__'
        read_only_fields = ['developer', 'api_key', 'created_at']


class AdDeveloperPushSerializer(serializers.ModelSerializer):
    app_name = serializers.CharField(source='app.app_name', read_only=True)
    ad_title = serializers.CharField(source='ad.title', read_only=True)

    class Meta:
        model = AdDeveloperPush
        fields = '__all__'


class PublicAdSerializer(serializers.ModelSerializer):
    target_areas = TargetAreaSerializer(many=True, read_only=True)
    target_audiences = TargetAudienceSerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    language_assets = AdLanguageAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Ad
        fields = [
            'id', 'title', 'description', 'target_areas',
            'target_audiences', 'languages', 'language_assets',
            'created_at',
        ]


class GeneratedMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedMedia
        fields = '__all__'
        read_only_fields = ['user', 'created_at']


class DeveloperAdListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_mobile = serializers.CharField(source='client.mobile', read_only=True)
    target_areas = TargetAreaSerializer(many=True, read_only=True)
    target_audiences = TargetAudienceSerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    language_assets = AdLanguageAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Ad
        fields = [
            'id', 'title', 'description', 'status', 'client_name', 'client_mobile',
            'target_areas', 'target_audiences', 'languages', 'language_assets',
            'final_asset', 'asset',
            'scheduled_start', 'scheduled_end',
            'created_at', 'updated_at',
        ]


class CreativeSessionListSerializer(serializers.ModelSerializer):
    asset_count = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = CreativeSession
        fields = ['id', 'title', 'media_type', 'created_at', 'updated_at', 'asset_count', 'preview_url']

    def get_asset_count(self, obj):
        return obj.events.filter(event_type='generate').count()

    def get_preview_url(self, obj):
        last_gen = obj.events.filter(event_type='generate', generated_media__isnull=False).last()
        if last_gen and last_gen.generated_media:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(last_gen.generated_media.file.url)
        return None


class CreativeSessionEventSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    model_used = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = CreativeSessionEvent
        fields = ['id', 'event_type', 'prompt', 'settings', 'file', 'model_used', 'duration_seconds', 'created_at']

    def get_file(self, obj):
        if obj.generated_media and obj.generated_media.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.generated_media.file.url)
            return obj.generated_media.file.url
        if obj.file:
            return obj.file
        return None

    def get_model_used(self, obj):
        return obj.generated_media.model_used if obj.generated_media else None

    def get_duration_seconds(self, obj):
        return obj.generated_media.duration_seconds if obj.generated_media else None


class CreativeSessionDetailSerializer(serializers.ModelSerializer):
    events = CreativeSessionEventSerializer(many=True, read_only=True)

    class Meta:
        model = CreativeSession
        fields = '__all__'
        read_only_fields = ['user', 'created_at', 'updated_at']


class CreativeSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreativeSession
        fields = ['id', 'title', 'media_type', 'settings', 'current_prompt']
