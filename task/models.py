from django.db import models


class TaskStatus(models.TextChoices):
    CREATED = 'Created'
    RUNNING = 'Running'
    PENDING = 'Pending'
    COMPLETED = 'Completed'
    FAILED = 'Failed'
    ERROR = 'Error'


# SLURM active (non-terminal) states - used for checking if a job is still running
SLURM_ACTIVE_STATES = frozenset({
    'PENDING', 'RUNNING', 'CONFIGURING', 'COMPLETING', 'REQUEUED', 'SUSPENDED',
    'CREATED', 'PENDING',
})

# Special pseudo job_id values (not real SLURM job IDs)
PSEUDO_JOB_IDS = frozenset({
    'viewer_only', 'skipped_existing', 'pending_hc', 'pending_he_scatter',
})


class tasks(models.Model):
    name = models.CharField(max_length=300, blank=True, null=True)
    user = models.CharField(max_length=300, blank=True, null=True)
    userpath = models.CharField(max_length=200, blank=True, null=True)

    task_type = models.CharField(max_length=60, blank=True, null=True)
    modulelist = models.CharField(max_length=400, blank=True, null=True)
    status = models.CharField(max_length=60, blank=True, null=True)
    task_detail = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tasks'
        verbose_name = 'tasks'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['user'], name='idx_tasks_user'),
        ]

    def __str__(self):
        return self.name
    
class SubTask(models.Model):
    main_task = models.ForeignKey(tasks, on_delete=models.CASCADE, related_name='subtasks')
    subtask_type = models.CharField(max_length=200)
    dataset_path = models.CharField(max_length=1000, blank=True, null=True)
    status = models.CharField(max_length=60, default=TaskStatus.CREATED, choices=TaskStatus.choices)
    job_id = models.CharField(max_length=100, blank=True, null=True)
    parameters = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SubTask'
        verbose_name_plural = verbose_name
        ordering = ['id']
        indexes = [
            models.Index(fields=['main_task', 'subtask_type', 'dataset_path'], name='idx_subtask_lookup'),
        ]

    def __str__(self):
        return f"{self.main_task.name} - {self.dataset_path} - {self.subtask_type} ({self.status})"

    def sync_from_slurm(self):
        """Query SLURM for current job status and update self.status.
        Returns the new status string, or None if SLURM could not be queried.
        Does not call .save() - caller is responsible for that.
        """
        from utils.slurm_api import normalize_slurm_status, get_job_status
        if not self.job_id or self.job_id in PSEUDO_JOB_IDS:
            return self.status
        raw_status = get_job_status(self.job_id)
        if not raw_status:
            return None
        normalized = normalize_slurm_status(raw_status)
        if normalized and normalized != self.status:
            self.status = normalized
        return normalized
