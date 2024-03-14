from rest_framework import serializers
from task.models import tasks

class taskSerializer(serializers.ModelSerializer):
    class Meta:
        model = tasks
        fields = ['id','name', 'user', 'uploadpath', 'analysis_type', 'modulelist', 'status', 'task_log', 'created_at']