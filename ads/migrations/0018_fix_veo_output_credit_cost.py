# Generated manually — fix double-counted credits in veo_output entries

from django.db import migrations


def fix_veo_output_credits(apps, schema_editor):
    ApiUsageLog = apps.get_model('ads', 'ApiUsageLog')
    updated = ApiUsageLog.objects.filter(
        model_id__contains='veo_output'
    ).exclude(credit_cost=0).update(credit_cost=0)
    if updated:
        print(f'Fixed {updated} veo_output entries: set credit_cost=0')


class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0017_apiusagelog_credit_cost'),
    ]

    operations = [
        migrations.RunPython(fix_veo_output_credits, migrations.RunPython.noop),
    ]
