from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset', '0004_dataset_citation_label_dataset_citation_url_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='dataset',
            index=models.Index(fields=['organ'], name='idx_dataset_organ'),
        ),
    ]
