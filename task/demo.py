"""Demo task construction: copy a pre-built real-result snapshot.

Try Demo creates a real tasks/SubTask graph that is already Completed. It
never submits SLURM work. The workspace is populated by copying a snapshot
of a REAL completed analysis (result/ + dataset_<uuid>/) from
user_data/demo_result/scst/<uuid>/, so every panel shows the genuine output
of that run. Real copies keep each demo workspace fully independent, so any
later cleanup of the snapshot source or of past demo tasks cannot break a
live demo.
"""

import json
import os

from scdb_api import settings_local as local_settings
from task.models import SubTask, TaskStatus, tasks
from task.services import MAPPING_DEPENDENT_TYPES


DEMO_DATASET_ID = 'Breast_Normal_002'
DEMO_TASK_NAME = 'Demo Task'
DEMO_JOB_ID = 'viewer_only'


def demo_task_parameters(dataset, taskname):
    """Production-shaped Scstquery params for a demo task.

    Scstquery.__init__ requires projectname/organParts/processType, so a demo
    taskdetail.json must contain them even though no pipeline ever runs.
    """
    organ = str(getattr(dataset, 'organ', '') or 'breast').lower()
    return {
        'projectname': taskname,
        'organParts': organ,
        'processType': 'celltype',
        'disease': 'all',
        'demo': True,
        'dataset_id': dataset.dataset_id,
    }


def find_demo_snapshot(dataset_title):
    """Locate the pre-built real-result snapshot for a dataset title.

    Checked in order:
      1. <repo root>/demo_result/scst/<title>  (gitignored; v1 convention)
      2. <USERTASKPATH>/demo_result/scst/<title> (preferred on the server:
         same filesystem as the task workspaces, so hardlinks work)
    """
    repo_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'demo_result', 'scst')
    )
    ws_root = os.path.normpath(os.path.join(local_settings.USERTASKPATH, 'demo_result', 'scst'))
    for root in (repo_root, ws_root):
        candidate = os.path.join(root, dataset_title)
        if os.path.isdir(candidate):
            return candidate
    return None


def task_is_demo(main_task):
    """True when the task's taskdetail.json marks it as a demo (demo: true)."""
    try:
        path = os.path.join(local_settings.USERTASKPATH, main_task.userpath, 'taskdetail.json')
        with open(path, 'r', encoding='utf-8') as f:
            entries = json.load(f)
    except Exception:
        return False
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(entry, dict) and (entry.get('parameters_dict') or {}).get('demo') is True
        for entry in entries
    )


def _copy_tree(src, dst):
    """Recursively copy every file under src into dst (real copies)."""
    import shutil
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _available_mapping_methods(ds_dir, subtask_type):
    """Mapping methods that actually have result files for a tool.

    Interaction tools (commot/cellchat/spider/alphatalk/lr_comparison) store
    outputs under result/sc_st_mapping/<method>/, while the scst_mapping
    subtask itself stores them directly under result/<method>/.
    """
    if subtask_type == 'scst_mapping':
        base = os.path.join(ds_dir, 'subtask_scst_mapping', 'result')
    else:
        base = os.path.join(ds_dir, f'subtask_{subtask_type}', 'result', 'sc_st_mapping')
    if not os.path.isdir(base):
        return []
    return sorted(
        name for name in os.listdir(base)
        if os.path.isdir(os.path.join(base, name))
        and any(os.scandir(os.path.join(base, name)))
    )


def demo_subtask_specs(ds_dir, dataset_id):
    """SubTask rows mirroring what the snapshot really contains.

    Every tool gets one row per mapping method that actually has result files
    in the snapshot (the pruned snapshot carries cytospace+tangram mapping
    outputs and tangram interaction data, plus he_scatter for commot/
    lr_comparison where the real run produced them), so the frontend per-
    method state restores to Completed exactly where data exists.
    """
    specs = []
    for method in _available_mapping_methods(ds_dir, 'scst_mapping'):
        specs.append(('scst_mapping', {'demo': True, 'dataset_id': dataset_id, 'mapping_method': method}))
    for st in ('he_scatter', 'hierarchical_clustering', 'annotation_mapping', 'recall_analysis'):
        specs.append((st, {'demo': True, 'dataset_id': dataset_id}))
    for tool in MAPPING_DEPENDENT_TYPES:
        for method in _available_mapping_methods(ds_dir, tool):
            specs.append((tool, {'demo': True, 'dataset_id': dataset_id, 'mapping_method': method}))
    for st in ('scgpt_embedding', 'umap_embedding', 'heatmap_embedding'):
        specs.append((st, {'demo': True, 'dataset_id': dataset_id}))
    return specs


def create_demo_task_rows(demo_task, dataset_id, ds_dir):
    """Create the Completed demo SubTask rows inside the caller's transaction."""
    for subtask_type, parameters in demo_subtask_specs(ds_dir, dataset_id):
        SubTask.objects.create(
            main_task=demo_task,
            subtask_type=subtask_type,
            dataset_path=dataset_id,
            status=TaskStatus.COMPLETED,
            job_id=DEMO_JOB_ID,
            parameters=parameters,
        )


def _write_organ_filtered_scores(task_abs_path, organ):
    """Keep only the demo organ's entries from the snapshot's real scores.

    The linked result_scores.json shares an inode with the snapshot, so it is
    unlinked before writing; the snapshot file itself is never modified.
    """
    scores_path = os.path.join(task_abs_path, 'result', 'sc_query', 'result_scores.json')
    if not os.path.isfile(scores_path):
        return
    with open(scores_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    filtered = {key: value for key, value in raw.items() if str(key).lower() == organ}
    if not filtered:
        return
    os.remove(scores_path)
    with open(scores_path, 'w', encoding='utf-8') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)


def build_demo_snapshot(task_abs_path, dataset, organ):
    """Populate the task workspace from the real-result snapshot.

    Copies result/ + dataset_<uuid>/ and filters the real result_scores.json
    to the demo organ so the card list stays scoped (the frontend enables only
    the demo dataset anyway). Raises FileNotFoundError when no snapshot exists
    so createDemoTask fails loudly instead of serving an empty demo.
    """
    uuid = dataset.title if dataset is not None else ''
    snapshot = find_demo_snapshot(uuid)
    if snapshot is None:
        raise FileNotFoundError(
            f'Demo snapshot not found for {uuid}; expected under '
            'user_data/demo_result/scst/ or <repo>/demo_result/scst/'
        )
    _copy_tree(os.path.join(snapshot, 'result'), os.path.join(task_abs_path, 'result'))
    ds_src = os.path.join(snapshot, f'dataset_{uuid}')
    if os.path.isdir(ds_src):
        _copy_tree(ds_src, os.path.join(task_abs_path, f'dataset_{uuid}'))
    _write_organ_filtered_scores(task_abs_path, organ)
    return snapshot
