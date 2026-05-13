from django.db import models


class tasks(models.Model):
    name = models.CharField(max_length=300, blank=True, null=True)
    user = models.CharField(max_length=300, blank=True, null=True)
    userpath = models.CharField(max_length=200, blank=True, null=True)

    task_type = models.CharField(max_length=60, blank=True, null=True)
    modulelist = models.CharField(max_length=400, blank=True, null=True)
    status = models.CharField(max_length=60, blank=True, null=True)
    #stage = models.CharField(max_length=60, blank=True, null=True)
    task_detail = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tasks'
        verbose_name = 'tasks'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name
    
class SubTask(models.Model):
    main_task = models.ForeignKey(tasks, on_delete=models.CASCADE, related_name='subtasks')
    subtask_type = models.CharField(max_length=200)  # 新增：原始子任务类型（如 "xx1"）
    dataset_path = models.CharField(max_length=1000, blank=True, null=True)
    status = models.CharField(max_length=60, default='Created')
    job_id = models.CharField(max_length=100, blank=True, null=True)
    parameters = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SubTask'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return f"{self.main_task.name} - {self.dataset_path} - {self.subtask_type} ({self.status})"
