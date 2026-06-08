from django.core.management.base import BaseCommand
from ads.models import Ad
from ads.services.veo import generate_video_from_text


class Command(BaseCommand):
    help = 'Generate a Veo 3 video for an ad'

    def add_arguments(self, parser):
        parser.add_argument('ad_id', type=int)

    def handle(self, *args, **options):
        ad = Ad.objects.get(id=options['ad_id'])
        prompt = ad.text_content or ad.description or ad.title
        self.stdout.write(f'Generating video for ad "{ad.title}"...')
        self.stdout.write(f'Prompt: {prompt[:100]}...')

        try:
            video_file = generate_video_from_text(prompt)
            ad.final_asset.save(video_file.name, video_file, save=True)
            ad.status = 'approved'
            ad.save()
            self.stdout.write(self.style.SUCCESS(f'Video saved as final_asset for ad {ad.id}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed: {e}'))
