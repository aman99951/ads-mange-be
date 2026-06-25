from django.db import migrations


def set_default_credits(apps, schema_editor):
    Manager = apps.get_model('accounts', 'Manager')
    Client = apps.get_model('accounts', 'Client')
    Manager.objects.filter(credit_balance=0).update(credit_balance=100)
    Client.objects.filter(credit_balance=0).update(credit_balance=50)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_client_credit_balance_manager_credit_balance_and_more'),
    ]

    operations = [
        migrations.RunPython(set_default_credits),
    ]
