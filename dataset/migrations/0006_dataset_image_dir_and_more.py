# Generated manually for Django 4.2.23 (local env has no Django; matches model fields)
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset', '0005_alter_dataset_cell_type_counts_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataset',
            name='image_dir',
            field=models.CharField(blank=True, default='', editable=False, max_length=300),
        ),
        migrations.AddField(
            model_name='dataset',
            name='image_h',
            field=models.IntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='dataset',
            name='image_w',
            field=models.IntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='dataset',
            name='scalef_raw',
            field=models.FloatField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='dataset',
            name='spot_diameter_fullres',
            field=models.FloatField(blank=True, editable=False, null=True),
        ),
    ]
