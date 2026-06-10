import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ad_generator.settings')

import django
django.setup()

from django.core.management import call_command
call_command('migrate', '--noinput')

from ad_generator.wsgi import application

app = application
