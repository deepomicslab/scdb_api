from task.serializers import taskSerializer
from django.core.management.base import BaseCommand, CommandError
from task.models import tasks, TaskStatus
from utils.slurm_api import normalize_slurm_status, get_job_status as slurm_get_job_status
import datetime, pickle, json, os
from scdb_api import settings_local as local_settings

# Raw SLURM terminal statuses (checked before normalization)
SLURM_TERMINAL_STATUSES = frozenset({
    'COMPLETED', 'CANCELLED', 'FAILED', 'TIMEOUT',
    'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'OUT_OF_MEMORY',
})


class Command(BaseCommand):
    help = 'Check and update status of running tasks from Slurm'

    def handle(self, *args, **options):
        tasklist = tasks.objects.filter(status__iexact='Running')

        for task in tasklist:
            try:
                if task.task_type != 'module':
                    continue

                base_path = os.path.join(local_settings.USERTASKPATH, task.userpath)
                jsonpath = os.path.join(base_path, 'taskdetail.json')
                pklpath = os.path.join(base_path, 'moduleobject.pkl')

                job_id = None
                try:
                    with open(jsonpath, 'r') as f:
                        jsondata = json.load(f)
                    detail = jsondata[0] if isinstance(jsondata, list) else jsondata
                    job_id = detail.get('job_id')
                except Exception:
                    pass

                if not job_id:
                    if os.path.exists(pklpath):
                        with open(pklpath, 'rb') as f:
                            taskobject = pickle.load(f)
                        job_id = taskobject.job_id
                    else:
                        task_id = task.id
                        task.delete()
                        self.stdout.write(self.style.WARNING(f'Metadata not found for task {task_id}, deleted from DB'))
                        self._append_change_log(f'Task {task_id} deleted from DB (metadata not found)')
                        continue

                raw_status = slurm_get_job_status(job_id)
                current_slurm_status = normalize_slurm_status(raw_status)

                if current_slurm_status and current_slurm_status.upper() in SLURM_TERMINAL_STATUSES:
                    task.status = current_slurm_status or TaskStatus.ERROR
                    task.save()

                    if os.path.exists(jsonpath):
                        with open(jsonpath, 'r') as f:
                            jsondata = json.load(f)
                        if isinstance(jsondata, list) and len(jsondata) > 0:
                            jsondata[0]['status'] = task.status
                            with open(jsonpath, 'w') as f:
                                json.dump(jsondata, f, ensure_ascii=False, indent=4)

                    self.stdout.write(self.style.SUCCESS(f'Task {task.id} updated to {task.status}'))
                    self._append_change_log(f'Task {task.id} updated to {task.status}')

            except Exception as e:
                error_msg = f'Error processing task {task.id}: {str(e)}'
                self.stdout.write(self.style.ERROR(error_msg))
        try:
            if (task.status or '').lower() == 'running':
                task.status = TaskStatus.FAILED
                task.save()
                self.stdout.write(self.style.WARNING(f'Task {task.id} marked Failed due to processing error'))
                self._append_change_log(f'Task {task.id} updated to {task.status}')
        except Exception:
            pass

    def _append_change_log(self, msg):
        """Write a line only for real changes (not on empty runs), so update.txt stops growing."""
        try:
            current_time = datetime.datetime.now()
            log_dir = "/home/platform/project/scdb_platform/scdb_api_logs"
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "update.txt")
            with open(log_path, 'a+') as f:
                f.write(f'{msg} at {str(current_time)}\n')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to write execution log: {e}'))
