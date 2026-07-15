import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AdsConfig(AppConfig):
    name = 'ads'

    def ready(self):
        self._configure_s3_cors()

    def _configure_s3_cors(self):
        """Configure S3 bucket CORS on startup so frontend can load media cross-origin."""
        import os
        bucket_name = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
        access_key = os.environ.get('AWS_ACCESS_KEY_ID', '')
        secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
        region = os.environ.get('AWS_S3_REGION_NAME', '')

        if not all([bucket_name, access_key, secret_key]):
            return

        try:
            import boto3
            s3 = boto3.client(
                's3',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region or 'us-east-1',
            )

            cors_rules = [{
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'HEAD'],
                'AllowedOrigins': ['*'],
                'ExposeHeaders': ['Content-Length', 'Content-Type', 'ETag'],
                'MaxAgeSeconds': 3600,
            }]

            existing = s3.get_bucket_cors(Bucket=bucket_name)
            existing_rules = existing.get('CORSRules', [])
            if existing_rules == cors_rules:
                return

            s3.put_bucket_cors(
                Bucket=bucket_name,
                CORSConfiguration={'CORSRules': cors_rules},
            )
            logger.info(f'S3 CORS configured for bucket: {bucket_name}')
        except Exception as e:
            logger.warning(f'Could not configure S3 CORS (manual setup may be needed): {e}')
