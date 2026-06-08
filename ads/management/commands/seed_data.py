from django.core.management.base import BaseCommand
from ads.models import TargetArea, TargetAudience


CHENNAI_LOCALITIES = [
    "T. Nagar", "Anna Nagar", "Adyar", "Besant Nagar", "Mylapore",
    "Nungambakkam", "Velachery", "Porur", "Guindy", "Chetpet",
    "Egmore", "Triplicane", "Thousand Lights", "Alwarpet", "Mambalam",
    "Koyambedu", "Arumbakkam", "Ashok Nagar", "Kodambakkam", "Teynampet",
    "Perungudi", "Sholinganallur", "Thoraipakkam", "Tambaram", "Chromepet",
    "Pallavaram", "Medavakkam", "Madipakkam", "Thiruvanmiyur", "Royapettah",
    "Saidapet", "Vadapalani", "Saligramam", "Virugambakkam", "Valasaravakkam",
    "Poonamallee", "Avadi", "Ambattur", "Mogappair", "Kolathur",
    "Villivakkam", "Perambur", "George Town", "Washermenpet", "Thondiarpet",
    "Tiruvottiyur", "Manali", "Minjur", "Red Hills", "Ennore",
]

AUDIENCE_PROFILES = [
    ("Electricians", 20, 55),
    ("Plumbers", 22, 60),
    ("Teachers", 24, 60),
    ("IT Professionals", 22, 50),
    ("Business Owners", 25, 65),
    ("Students", 18, 28),
    ("Healthcare Workers", 22, 60),
    ("Homemakers", 25, 55),
    ("Delivery Partners", 18, 45),
    ("Restaurant Owners", 25, 55),
    ("Shopkeepers", 22, 60),
    ("Real Estate Agents", 25, 60),
    ("Beauty & Salon Professionals", 20, 50),
    ("Auto & Cab Drivers", 22, 55),
    ("Construction Workers", 22, 50),
]


class Command(BaseCommand):
    help = "Seed target areas and audiences"

    def handle(self, *args, **options):
        created_areas = 0
        for locality in CHENNAI_LOCALITIES:
            _, was_created = TargetArea.objects.get_or_create(
                state="Tamil Nadu",
                city="Chennai",
                locality=locality,
            )
            if was_created:
                created_areas += 1

        created_audiences = 0
        for profile, age_min, age_max in AUDIENCE_PROFILES:
            _, was_created = TargetAudience.objects.get_or_create(
                profile=profile,
                age_min=age_min,
                age_max=age_max,
            )
            if was_created:
                created_audiences += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_areas} target areas and {created_audiences} target audiences"
        ))
