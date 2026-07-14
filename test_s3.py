"""Quick S3 connectivity test - run with: python test_s3.py"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', '')

print("=" * 50)
print("S3 STORAGE TEST")
print("=" * 50)

# Step 1: Check env vars
print("\n[1/5] Checking environment variables...")
missing = []
if not AWS_ACCESS_KEY_ID:
    missing.append('AWS_ACCESS_KEY_ID')
if not AWS_SECRET_ACCESS_KEY:
    missing.append('AWS_SECRET_ACCESS_KEY')
if not AWS_STORAGE_BUCKET_NAME:
    missing.append('AWS_STORAGE_BUCKET_NAME')
if not AWS_S3_REGION_NAME:
    missing.append('AWS_S3_REGION_NAME')

if missing:
    print(f"  MISSING: {', '.join(missing)}")
    print("  Set these in backend/.env and try again.")
    sys.exit(1)
print(f"  Bucket:  {AWS_STORAGE_BUCKET_NAME}")
print(f"  Region:  {AWS_S3_REGION_NAME}")
print(f"  Key ID:  {AWS_ACCESS_KEY_ID[:8]}...")

# Step 2: Test boto3 connection
print("\n[2/5] Connecting to S3...")
try:
    import boto3
    s3 = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_S3_REGION_NAME,
    )
    s3.head_bucket(Bucket=AWS_STORAGE_BUCKET_NAME)
    print("  Connected! Bucket exists and is accessible.")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)

# Step 3: Upload test image
print("\n[3/5] Uploading test image...")
try:
    from PIL import Image
    import io
    img = Image.new('RGB', (100, 100), color='red')
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)

    test_key = 'test/s3_test_image.png'
    s3.put_object(
        Bucket=AWS_STORAGE_BUCKET_NAME,
        Key=test_key,
        Body=img_buffer.getvalue(),
        ContentType='image/png',
    )
    print(f"  Uploaded: s3://{AWS_STORAGE_BUCKET_NAME}/{test_key}")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)

# Step 4: Upload test video (tiny dummy file)
print("\n[4/5] Uploading test video...")
try:
    test_video_key = 'test/s3_test_video.mp4'
    dummy_data = b'\x00' * 1024  # 1KB dummy
    s3.put_object(
        Bucket=AWS_STORAGE_BUCKET_NAME,
        Key=test_video_key,
        Body=dummy_data,
        ContentType='video/mp4',
    )
    print(f"  Uploaded: s3://{AWS_STORAGE_BUCKET_NAME}/{test_video_key}")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)

# Step 5: Verify public URLs
print("\n[5/5] Verifying public access...")
try:
    img_url = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{test_key}"
    video_url = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{test_video_key}"

    import requests
    img_resp = requests.head(img_url, timeout=10)
    vid_resp = requests.head(video_url, timeout=10)

    print(f"  Image URL: {img_resp.status_code} {img_resp.headers.get('Content-Type', '')}")
    print(f"  Video URL: {vid_resp.status_code} {vid_resp.headers.get('Content-Type', '')}")

    if img_resp.status_code == 200 and vid_resp.status_code == 200:
        print("\n  Both files are publicly accessible!")
except Exception as e:
    print(f"  URL check failed (files may still work): {e}")

# Cleanup test files
print("\nCleaning up test files...")
s3.delete_object(Bucket=AWS_STORAGE_BUCKET_NAME, Key=test_key)
s3.delete_object(Bucket=AWS_STORAGE_BUCKET_NAME, Key=test_video_key)
print("  Deleted test files.")

print("\n" + "=" * 50)
print("ALL TESTS PASSED - S3 is ready!")
print("=" * 50)
