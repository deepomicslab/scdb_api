from rest_framework import serializers
from task.models import tasks


    # name = models.CharField(max_length=300, blank=True, null=True)
    # user = models.CharField(max_length=300, blank=True, null=True)
    # userpath = models.CharField(max_length=200, blank=True, null=True)

    # task_type = models.CharField(max_length=60, blank=True, null=True)
    # modulelist = models.CharField(max_length=400, blank=True, null=True)
    # status = models.CharField(max_length=60, blank=True, null=True)
    # #stage = models.CharField(max_length=60, blank=True, null=True)
    # task_detail = models.TextField(blank=True, null=True)
    # created_at = models.DateTimeField(auto_now_add=True)

class taskSerializer(serializers.ModelSerializer):
    class Meta:
        model = tasks
        fields = ['id','name', 'user', 'userpath', 'task_type', 'modulelist', 'status', 'created_at']