from rest_framework import serializers
from .models import TargetArea, TargetAudience, Ad, AdIteration


class TargetAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetArea
        fields = '__all__'


class TargetAudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetAudience
        fields = '__all__'


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
            'created_at', 'updated_at'
        ]


class AdDetailSerializer(serializers.ModelSerializer):
    target_areas = TargetAreaSerializer(many=True, read_only=True)
    target_audiences = TargetAudienceSerializer(many=True, read_only=True)
    target_area_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    target_audience_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    iterations = AdIterationSerializer(many=True, read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_mobile = serializers.CharField(source='client.mobile', read_only=True)

    class Meta:
        model = Ad
        fields = [
            'id', 'client', 'title', 'description', 'target_areas',
            'target_audiences', 'target_area_ids', 'target_audience_ids',
            'asset', 'text_content', 'status', 'admin_feedback', 'final_asset',
            'generation_error', 'client_name', 'client_mobile',
            'created_at', 'updated_at', 'iterations'
        ]
        read_only_fields = ['client', 'status', 'admin_feedback', 'final_asset', 'generation_error', 'created_at', 'updated_at', 'iterations']

    def create(self, validated_data):
        target_area_ids = validated_data.pop('target_area_ids', [])
        target_audience_ids = validated_data.pop('target_audience_ids', [])
        ad = Ad.objects.create(**validated_data)
        if target_area_ids:
            ad.target_areas.set(TargetArea.objects.filter(id__in=target_area_ids))
        if target_audience_ids:
            ad.target_audiences.set(TargetAudience.objects.filter(id__in=target_audience_ids))
        return ad


class AdStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ad
        fields = ['status', 'admin_feedback', 'final_asset', 'generation_error']
