# Generated manually for Django 4.2.23 (local env has no Django; matches model fields)
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dataset', '0006_dataset_image_dir_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dataset',
            name='image_h',
        ),
        migrations.RemoveField(
            model_name='dataset',
            name='image_w',
        ),
    ]
