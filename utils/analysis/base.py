import os
import json
from utils import slurm_api
from utils.slurm_api import normalize_slurm_status
from scdb_api import settings_local as local_settings
from utils.mapping_paths import list_completed_methods, resolve_mapping_output_path
from task.models import TaskStatus
from dataset.models import Dataset


def extract_dataset_uuid(dataset_path):
    """Extract UUID from dataset_path (format: .../<uuid>/st_marker/...).
    Returns None if parsing fails."""
    parts = dataset_path.split('/')
    for i, p in enumerate(parts):
        if p == 'st_marker' and i > 1:
            return parts[i - 1]
    return None


def resolve_marker_path(task_dir, dataset_id):
    """Resolve a dataset's marker CSV path on the server side.

    Server paths must never reach the browser, so the frontend only passes
    dataset_id and the backend recovers the marker path here: read the keys of
    result/sc_query/result_scores.json (marker paths written by the main
    pipeline) and match via     dataset_id -> Dataset.title (uuid).
    Returns the path string, or None when unresolvable.
    """
    try:
        uuid = Dataset.objects.get(dataset_id=dataset_id).title
    except Dataset.DoesNotExist:
        return None
    scores_path = os.path.join(
        local_settings.USERTASKPATH + task_dir, 'result/sc_query/result_scores.json'
    )
    if not os.path.exists(scores_path):
        return None
    try:
        with open(scores_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except Exception:
        return None
    for organ_datasets in raw_data.values():
        if not isinstance(organ_datasets, dict):
            continue
        for original_path in organ_datasets.keys():
            if extract_dataset_uuid(original_path) == uuid:
                return original_path
    return None


class Module:
    def __init__(self, name,userpath):
        self.name = name
        self.job_id = None
        self.dependencies = []
        self.path = local_settings.USERTASKPATH+userpath
        self.status = TaskStatus.CREATED
        self.shell_script = None
        self.script_arguments = None

    def add_dependency(self, module):
        if not isinstance(module, Module):
            raise TypeError("Dependency must be an instance of Module or its subclasses.")
        self.dependencies.append(module)

    def _dataset_dir_key(self, dataset_id):
        """dataset_<key> result-dir key, sourced from the Dataset table by dataset_id
        (returns Dataset.title). Write/read/listing all use this so the dir matches
        across create, status-poll and download -- no more basename-vs-path-parsing drift."""
        try:
            return Dataset.objects.get(dataset_id=dataset_id).title
        except Dataset.DoesNotExist:
            return None

    def _scstmappingStatusFallback(self, dataset_id):
        from task.models import SubTask as SubTaskModel, tasks as task_model
        try:
            uuid = self._dataset_dir_key(dataset_id)
            if not uuid:
                return {'completed_methods': [], 'running_methods': [], 'status': 'error', 'message': 'Cannot resolve dataset UUID'}
            methods = list_completed_methods(self.path, uuid)
            # Filter by main_task to prevent cross-task status leaking
            userpath = self.path.replace(local_settings.USERTASKPATH, '')
            main_task = task_model.objects.get(userpath=userpath)
            from django.db.models import Q
            # Collect ALL concurrently-running mapping methods. cytospace/tangram run
            # as scst_mapping subtasks; he_scatter/hc run as their own subtask types
            # (triggered by annotation-mapping / recall-analysis auto-chain).
            running_qs = SubTaskModel.objects.filter(
                main_task=main_task,
                subtask_type__in=['scst_mapping', 'he_scatter', 'hierarchical_clustering', 'lr_comparison'],
                dataset_path=dataset_id,
            ).filter(
                Q(status__iexact='created') | Q(status__iexact='pending') | Q(status__iexact='running')
            ).order_by('-id')
            # Sync each active mapping subtask's real SLURM status into the DB
            # before classifying, so running/failed reflect reality (frontend polls
            # this endpoint automatically, and the Refresh button also routes here).
            for st in running_qs:
                try:
                    prev_status = st.status
                    new_status = st.sync_from_slurm()
                    if new_status and new_status != prev_status:
                        st.save()
                except Exception:
                    pass

            running_methods = []
            seen = set()
            for st in running_qs:
                params = st.parameters if isinstance(st.parameters, dict) else {}
                if st.subtask_type in ('scst_mapping', 'lr_comparison'):
                    m = params.get('mapping_method')
                elif st.subtask_type == 'he_scatter':
                    m = 'he_scatter'
                elif st.subtask_type == 'hierarchical_clustering':
                    m = 'hierarchical_clustering'
                else:
                    m = None
                if m and m not in seen:
                    seen.add(m)
                    running_methods.append(m)
            # Collect failed mapping methods (non-completed, non-active terminal states)
            failed_qs = SubTaskModel.objects.filter(
                main_task=main_task,
                subtask_type__in=['scst_mapping', 'he_scatter', 'hierarchical_clustering', 'lr_comparison'],
                dataset_path=dataset_id,
            ).exclude(
                Q(status__iexact='created') | Q(status__iexact='pending') | Q(status__iexact='running')
                | Q(status__iexact='completed')
            ).order_by('-id')
            failed_methods = []
            seen_failed = set()
            for st in failed_qs:
                params = st.parameters if isinstance(st.parameters, dict) else {}
                if st.subtask_type in ('scst_mapping', 'lr_comparison'):
                    m = params.get('mapping_method')
                elif st.subtask_type == 'he_scatter':
                    m = 'he_scatter'
                elif st.subtask_type == 'hierarchical_clustering':
                    m = 'hierarchical_clustering'
                else:
                    m = None
                if m and m not in seen_failed:
                    seen_failed.add(m)
                    failed_methods.append({'method': m, 'subtask_id': st.id})
            return {'completed_methods': methods, 'running_methods': running_methods, 'failed_methods': failed_methods, 'status': 'success'}
        except Exception as e:
            return {'completed_methods': [], 'running_methods': [], 'failed_methods': [], 'status': 'error', 'message': str(e)}

    def _extract_dataset_uuid(self, dataset_path):
        """Extract UUID from dataset_path (format: .../<uuid>/st_marker/...).
        Returns None if parsing fails."""
        return extract_dataset_uuid(dataset_path)

    def _scstmapping_resolve_file(self, dataset_id, method):
        """Resolve mapping result h5ad path for streaming download.
        Returns {'_stream_file': abs_path, 'filename': fname} on success -- the view
        turns this into a FileResponse -- or {'status': 'fail', 'message': ...} on error.
        Never raises. (Replaces the old base64-into-JSON body so multi-MB h5ad files are
        streamed instead of loaded into memory + atob'd on the client.)"""
        try:
            uuid = self._dataset_dir_key(dataset_id)
            if not uuid:
                return {'status': 'fail', 'message': 'Cannot resolve dataset UUID'}
            try:
                h5ad_path = resolve_mapping_output_path(self.path, uuid, method)
            except ValueError as e:
                return {'status': 'fail', 'message': str(e)}
            if not os.path.isfile(h5ad_path):
                return {'status': 'fail', 'message': f'No mapping file found: input_sc_spatial.h5ad'}
            return {'_stream_file': h5ad_path, 'filename': 'input_sc_spatial.h5ad'}
        except Exception as e:
            return {'status': 'fail', 'message': str(e)}

    def check_status(self):
        if self.job_id is None:
            raise ValueError("Job ID is not set. Cannot check status.")
        raw_status = slurm_api.get_job_status(self.job_id)
        self.status = normalize_slurm_status(raw_status) or self.status
        return self.status

    def process(self):

        if self.shell_script is None:
            raise ValueError("Shell script is not set. Cannot process module.")
        if len(self.dependencies) == 0:
            #print(self.shell_script,self.script_arguments)
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments)
        else:
            dependencies_jobs = [dependency.job_id for dependency in self.dependencies if dependency.job_id is not None]
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments,dependency_job_ids=dependencies_jobs)
        self.status = TaskStatus.RUNNING
        return self.job_id
