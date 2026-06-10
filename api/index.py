import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ad_generator.settings')

import django
django.setup()

from django.core.management import call_command
call_command('migrate', '--noinput')

from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='l', first_name='Super Admin')
    print('Superuser "admin" created')

from ad_generator.wsgi import application

app = application
