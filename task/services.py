"""Service layer for task/subtask creation.

Extracts business logic from views.py create_subtask and createtask,
providing a clean API with module whitelist and prerequisite chaining.
"""
import os
import json

from task.models import tasks, SubTask, TaskStatus
from dataset.models import Dataset
from utils.mapping_paths import check_mapping_completed
from scdb_api import settings_local as local_settings
import utils.analysis


# Module whitelist registry (replaces unsafe getattr)
# Only these classes can be instantiated from user input
MODULE_REGISTRY = {
    'Scquery': utils.analysis.Scquery,
    'Scstquery': utils.analysis.Scstquery,
    'SubScstquery': utils.analysis.SubScstquery,
}


# Prerequisite chain config: subtask_type -> prereq config
# When a subtask requires a prerequisite (e.g. HC for recall_analysis),
# the prerequisite is auto-submitted to SLURM before the main subtask.
PREREQUISITE_CHAIN = {
    'recall_analysis': {
        'prereq_type': 'hierarchical_clustering',
        'subtask_id_key': '_hc_subtask_id',
        'job_id_key': '_hc_job_id',
    },
    'annotation_mapping': {
        'prereq_type': 'he_scatter',
        'subtask_id_key': '_hs_subtask_id',
        'job_id_key': '_hs_job_id',
    },
    'umap_embedding': {
        'prereq_type': 'scgpt_embedding',
        'subtask_id_key': '_scgpt_subtask_id',
        'job_id_key': '_scgpt_job_id',
    },
    'heatmap_embedding': {
        'prereq_type': 'scgpt_embedding',
        'subtask_id_key': '_scgpt_subtask_id',
        'job_id_key': '_scgpt_job_id',
    },
}

# Statuses for which an existing prerequisite subtask can be reused instead of
# re-submitting a duplicate SLURM job (UMAP/Heatmap share one scgpt_embedding).
PREREQ_REUSE_STATUSES = ('COMPLETED', 'RUNNING', 'PENDING', 'CREATED')

# Subtask types that require a completed SC-ST Mapping before they can run
MAPPING_DEPENDENT_TYPES = ('commot', 'cellchat', 'spider', 'alphatalk', 'lr_comparison')


def get_module_class(module_name):
    """Look up a module class by name from the whitelist registry.
    Returns None if not found.
    """
    return MODULE_REGISTRY.get(module_name)


class ExistingJobModule(utils.analysis.base.Module):
    """Minimal Module wrapper carrying an already-submitted SLURM job_id.

    Used when a prerequisite (e.g. scgpt_embedding) already exists for the same
    main task + dataset: the viewer depends on it without re-submitting a job.
    """

    def __init__(self, job_id):
        super().__init__(name='existing_prereq', userpath='')
        self.job_id = job_id


def _chain_prerequisite(cls, prereq_type, usertask_dir, dataset_uuid,
                        dataset_path, st_h5ad_path, params, main_task, dataset_id):
    """Auto-submit a prerequisite subtask (HC or HE scatter) to SLURM.

    Returns (job_id, subtask_id) if submitted, or (None, None) if not.
    """
    prereq_params = params.copy()
    prereq_params['sub_type'] = prereq_type
    if 'organParts' not in prereq_params:
        prereq_params['organParts'] = ''
    if 'projectname' not in prereq_params:
        prereq_params['projectname'] = 'test'

    prereq_module = cls(prereq_type, usertask_dir, dataset_uuid,
                        dataset_path, st_h5ad_path, prereq_params)
    prereq_job_id = prereq_module.process()
    if not prereq_job_id:
        return None, None

    prereq_subtask = SubTask.objects.create(
        main_task=main_task,
        subtask_type=prereq_type,
        dataset_path=dataset_id,
        status=TaskStatus.RUNNING,
        job_id=prereq_job_id,
        parameters=prereq_params,
    )
    print(f'Auto-created {prereq_type} subtask id={prereq_subtask.id}, job_id={prereq_job_id}')
    return prereq_module, prereq_job_id, prereq_subtask


def create_subtask(main_task, userid, dataset_id, subtasktype, parameters_dict):
    """Create and submit a subtask.

    The server resolves the marker path by dataset_id; it no longer accepts a
    server path sent by the client.
    Returns dict: {'status', 'message', 'data': {'subtaskid'}}
    Raises ValueError for validation failures.
    """
    from utils.analysis.base import resolve_marker_path

    usertask_dir = main_task.userpath
    parameters_dict['userid'] = userid
    parameters_dict['dataset_id'] = dataset_id
    if 'projectname' not in parameters_dict:
        parameters_dict['projectname'] = 'test'

    # Create subtask DB record
    new_subtask = SubTask.objects.create(
        main_task=main_task,
        subtask_type=subtasktype,
        dataset_path=dataset_id,
        status=TaskStatus.CREATED,
        parameters=parameters_dict,
    )

    cls = MODULE_REGISTRY.get('SubScstquery')
    if cls is None:
        raise ValueError('SubScstquery module not found')

    # Resolve dataset info
    dataset_uuid = ''
    st_h5ad_path = ''
    if dataset_id:
        try:
            ds = Dataset.objects.get(dataset_id=dataset_id)
            dataset_uuid = ds.title
            st_h5ad_path = ds.file_path
        except Dataset.DoesNotExist:
            pass

    # Resolve marker CSV path server-side (only types that feed it to SLURM
    # scripts require it; annotation_mapping/recall_analysis need it via
    # their auto-chained he_scatter/hierarchical_clustering prerequisite).
    dataset_path = resolve_marker_path(usertask_dir, dataset_id) if dataset_id else None
    PATH_REQUIRED_TYPES = ('he_scatter', 'hierarchical_clustering',
                           'annotation_mapping', 'recall_analysis')
    if subtasktype in PATH_REQUIRED_TYPES and not dataset_path:
        new_subtask.status = TaskStatus.FAILED
        new_subtask.save()
        raise ValueError(
            f"Cannot resolve marker path for dataset {dataset_id}; "
            "has the main SC-ST query finished?"
        )

    new_submodule = cls(subtasktype, usertask_dir, dataset_uuid,
                        dataset_path or '', st_h5ad_path, parameters_dict)

    # Auto-chain prerequisites (HC for recall_analysis, HE for annotation_mapping,
    # scgpt_embedding for umap/heatmap viewers)
    chain_config = PREREQUISITE_CHAIN.get(subtasktype)
    if chain_config:
        # Reuse an existing prerequisite for the same task + dataset (UMAP and
        # Heatmap share one scgpt_embedding compute job instead of running twice).
        existing_prereq = SubTask.objects.filter(
            main_task=main_task,
            subtask_type=chain_config['prereq_type'],
            dataset_path=dataset_id,
        ).order_by('-id').first()
        reuse = (existing_prereq is not None
                 and not parameters_dict.get('force_rerun')
                 and (existing_prereq.status or '').upper() in PREREQ_REUSE_STATUSES)
        if reuse:
            parameters_dict[chain_config['subtask_id_key']] = existing_prereq.id
            parameters_dict[chain_config['job_id_key']] = existing_prereq.job_id
            if (existing_prereq.status or '').upper() != 'COMPLETED':
                new_submodule.add_dependency(ExistingJobModule(existing_prereq.job_id))
        else:
            result = _chain_prerequisite(
                cls, chain_config['prereq_type'], usertask_dir, dataset_uuid,
                dataset_path or '', st_h5ad_path, parameters_dict, main_task, dataset_id
            )
            if result[0]:  # prereq_module
                prereq_module, prereq_job_id, prereq_subtask = result
                new_submodule.add_dependency(prereq_module)
                parameters_dict[chain_config['subtask_id_key']] = prereq_subtask.id
                parameters_dict[chain_config['job_id_key']] = prereq_job_id

    # Explicit mapping dependency check for commot/cellchat/spider
    if subtasktype in MAPPING_DEPENDENT_TYPES:
        mapping_method = parameters_dict.get('mapping_method', 'cytospace')
        mapping_base = os.path.join(local_settings.USERTASKPATH, usertask_dir)
        if not check_mapping_completed(mapping_base, dataset_uuid, mapping_method):
            new_subtask.status = TaskStatus.FAILED
            new_subtask.save()
            raise ValueError(
                f"SC-ST Mapping ({mapping_method}) has not completed. Please run it first."
            )

    # Submit the main subtask
    job_id = new_submodule.process()

    new_subtask.job_id = job_id
    new_subtask.status = new_submodule.status if new_submodule.status else TaskStatus.RUNNING
    new_subtask.parameters = parameters_dict
    new_subtask.save()

    return {
        'status': 'Success',
        'message': 'Subtask created successfully',
        'data': {'subtaskid': new_subtask.id},
    }
