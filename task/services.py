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
}

# Subtask types that require a completed SC-ST Mapping before they can run
MAPPING_DEPENDENT_TYPES = ('commot', 'cellchat', 'spider', 'alphatalk')


def get_module_class(module_name):
    """Look up a module class by name from the whitelist registry.
    Returns None if not found.
    """
    return MODULE_REGISTRY.get(module_name)


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


def create_subtask(main_task, userid, dataset_path, dataset_id, subtasktype, parameters_dict):
    """Create and submit a subtask.

    Returns dict: {'status', 'message', 'data': {'subtaskid', 'sub_dir'}}
    Raises ValueError for validation failures.
    """
    usertask_dir = main_task.userpath
    parameters_dict['userid'] = userid
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

    new_submodule = cls(subtasktype, usertask_dir, dataset_uuid,
                        dataset_path, st_h5ad_path, parameters_dict)

    # Auto-chain prerequisites (HC for recall_analysis, HE for annotation_mapping)
    chain_config = PREREQUISITE_CHAIN.get(subtasktype)
    if chain_config:
        result = _chain_prerequisite(
            cls, chain_config['prereq_type'], usertask_dir, dataset_uuid,
            dataset_path, st_h5ad_path, parameters_dict, main_task, dataset_id
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
        'message': '子任务创建成功',
        'data': {'subtaskid': new_subtask.id, 'sub_dir': new_submodule.path},
    }
