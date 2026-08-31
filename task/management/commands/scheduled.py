from task.serializers import taskSerializer
from django.core.management.base import BaseCommand, CommandError
from task.models import tasks, TaskStatus, SubTask, PSEUDO_JOB_IDS
from utils.slurm_api import normalize_slurm_status, get_job_status as slurm_get_job_status
import datetime, pickle, json, os
from django.utils import timezone
from scdb_api import settings_local as local_settings

# Raw SLURM terminal statuses (checked before normalization)
SLURM_TERMINAL_STATUSES = frozenset({
    'COMPLETED', 'CANCELLED', 'FAILED', 'TIMEOUT',
    'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'OUT_OF_MEMORY',
})

# How long a Running task may stay invisible to squeue/sacct before it is
# considered stale and marked Failed. This covers cases where the web service
# was interrupted and the SLURM record was also lost; transient SLURM outages
# shorter than this window keep the task Running and retry on the next sync.
SLURM_MISSING_TIMEOUT = datetime.timedelta(hours=1)


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

                if current_slurm_status:
                    # SLURM resolved the job again (active or terminal):
                    # clear the missing-since timer if it was set.
                    if task.slurm_missing_since is not None:
                        task.slurm_missing_since = None
                        task.save(update_fields=['slurm_missing_since'])
                else:
                    # squeue + sacct both failed to resolve the job. Keep the
                    # task Running for a grace period (transient SLURM outage),
                    # then mark it Failed if the job remains invisible.
                    now = timezone.now()
                    if task.slurm_missing_since is None:
                        task.slurm_missing_since = now
                        task.save(update_fields=['slurm_missing_since'])
                    elif now - task.slurm_missing_since >= SLURM_MISSING_TIMEOUT:
                        task.status = TaskStatus.FAILED
                        task.slurm_missing_since = None
                        task.save(update_fields=['status', 'slurm_missing_since'])

                        if os.path.exists(jsonpath):
                            try:
                                with open(jsonpath, 'r') as f:
                                    jsondata = json.load(f)
                                if isinstance(jsondata, list) and len(jsondata) > 0:
                                    jsondata[0]['status'] = task.status
                                    with open(jsonpath, 'w') as f:
                                        json.dump(jsondata, f, ensure_ascii=False, indent=4)
                            except Exception:
                                pass

                        self.stdout.write(self.style.WARNING(
                            f'Task {task.id} marked Failed: SLURM job {job_id} not found for {SLURM_MISSING_TIMEOUT}'
                        ))
                        self._append_change_log(
                            f'Task {task.id} updated to {task.status} (SLURM job missing)'
                        )
                        continue

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

        # Sync active subtasks that are stuck in Running/Pending but SLURM already finished.
        # Frontend polling (subtask_status_update) also syncs, but it requires the
        # browser to be open and the backend to be up. This background sync covers
        # the gap when the web service was down or the user navigated away.
        try:
            active_statuses = ['Running', 'Pending', 'Created', 'Configuring', 'Completing', 'Requeued', 'Suspended']
            active_subtasks = SubTask.objects.filter(status__in=active_statuses).exclude(job_id__in=PSEUDO_JOB_IDS).exclude(job_id__isnull=True).exclude(job_id__exact='')
            for st in active_subtasks:
                try:
                    prev = st.status
                    new_status = st.sync_from_slurm()
                    if new_status and new_status != prev:
                        st.save(update_fields=['status', 'updated_at'])
                        self.stdout.write(self.style.SUCCESS(f'SubTask {st.id} ({st.subtask_type}) {prev} -> {new_status}'))
                        self._append_change_log(f'SubTask {st.id} updated to {new_status}')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'SubTask {st.id} sync failed: {e}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'SubTask sync pass failed: {e}'))

        # Sync pending viewers that wait for a prerequisite (HC/HE/scgpt).
        # If the prerequisite Completed, the viewer becomes Completed (viewer_only);
        # if it Failed, the viewer also becomes Failed so the UI does not stay
        # Pending forever (frontend polling also handles this, but this covers
        # the gap when the browser is closed).
        try:
            pending_map = {
                'pending_hc': ('recall_analysis', 'hierarchical_clustering'),
                'pending_he_scatter': ('annotation_mapping', 'he_scatter'),
                'pending_scgpt': (('umap_embedding', 'heatmap_embedding'), 'scgpt_embedding'),
            }
            for pending_job, (viewer_types, prereq_type) in pending_map.items():
                if isinstance(viewer_types, str):
                    viewer_types = (viewer_types,)
                viewers = SubTask.objects.filter(job_id=pending_job, subtask_type__in=viewer_types, status__iexact='Pending')
                for v in viewers:
                    prereq = SubTask.objects.filter(
                        main_task=v.main_task, subtask_type=prereq_type, dataset_path=v.dataset_path
                    ).order_by('-id').first()
                    if not prereq:
                        continue
                    # Sync the prerequisite's SLURM status first
                    try:
                        prereq_new = prereq.sync_from_slurm()
                        if prereq_new and prereq_new != prereq.status:
                            prereq.save(update_fields=['status', 'updated_at'])
                    except Exception:
                        pass
                    prereq_upper = (prereq.status or '').upper()
                    if prereq_upper == 'COMPLETED':
                        v.status = TaskStatus.COMPLETED
                        v.job_id = 'viewer_only'
                        v.save(update_fields=['status', 'job_id', 'updated_at'])
                        self.stdout.write(self.style.SUCCESS(f'Pending viewer {v.id} -> Completed (prereq {prereq.id} completed)'))
                        self._append_change_log(f'SubTask {v.id} updated to Completed (prereq completed)')
                    elif prereq_upper == 'FAILED':
                        v.status = TaskStatus.FAILED
                        v.save(update_fields=['status', 'updated_at'])
                        self.stdout.write(self.style.WARNING(f'Pending viewer {v.id} -> Failed (prereq {prereq.id} failed)'))
                        self._append_change_log(f'SubTask {v.id} updated to Failed (prereq failed)')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Pending viewer sync failed: {e}'))

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
