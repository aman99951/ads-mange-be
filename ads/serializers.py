from rest_framework import serializers
from .models import TargetArea, TargetAudience, Language, Ad, AdIteration, AdLanguageAsset, DeveloperApp, AdDeveloperPush


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
            'created_at', 'updated_at', 'iterations'
        ]
        read_only_fields = ['client', 'status', 'admin_feedback', 'final_asset', 'generation_error', 'created_at', 'updated_at', 'iterations']

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
