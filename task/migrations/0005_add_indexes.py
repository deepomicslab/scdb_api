from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('task', '0004_rename_dataset_id_subtask_dataset_path'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tasks',
            index=models.Index(fields=['user'], name='idx_tasks_user'),
        ),
        migrations.AddIndex(
            model_name='subtask',
            index=models.Index(fields=['main_task', 'subtask_type', 'dataset_path'], name='idx_subtask_lookup'),
        ),
    ]
