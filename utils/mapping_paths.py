"""Single source of truth for SC-ST mapping output file paths.

All mapping method -> file path resolution goes through here.
Previously duplicated in 4 places (views.py, analysis.py x3) with
slightly different logic, causing path-drift bugs.
"""
import os

MAPPING_OUTPUT_FILENAME = 'input_sc_spatial.h5ad'

ALL_METHODS = ('cytospace', 'tangram', 'he_scatter', 'hierarchical_clustering')


def get_mapping_output_subpath(method):
    """Return the relative path (from dataset_{uuid}/) to the mapping output file.

    cytospace/tangram      -> subtask_scst_mapping/result/{method}/input_sc_spatial.h5ad
    he_scatter             -> subtask_he_scatter/result/input_sc_spatial.h5ad
    hierarchical_clustering -> subtask_hierarchical_clustering/result/input_sc_spatial.h5ad

    Raises ValueError for unknown method.
    """
    if method in ('cytospace', 'tangram'):
        return os.path.join('subtask_scst_mapping', 'result', method, MAPPING_OUTPUT_FILENAME)
    elif method == 'he_scatter':
        return os.path.join('subtask_he_scatter', 'result', MAPPING_OUTPUT_FILENAME)
    elif method == 'hierarchical_clustering':
        return os.path.join('subtask_hierarchical_clustering', 'result', MAPPING_OUTPUT_FILENAME)
    else:
        raise ValueError(f'Unknown mapping method: {method}')


def resolve_mapping_output_path(base_dir, dataset_uuid, method):
    """Return the full path to a mapping output file.

    base_dir: the user task directory (e.g. USERTASKPATH + userpath, or self.path)
    dataset_uuid: Dataset.title (used as dataset_{uuid} dir key)
    method: one of ALL_METHODS
    """
    subpath = get_mapping_output_subpath(method)
    return os.path.join(base_dir, f'dataset_{dataset_uuid}', subpath)


def check_mapping_completed(base_dir, dataset_uuid, method):
    """Return True if the mapping output file exists for the given method."""
    path = resolve_mapping_output_path(base_dir, dataset_uuid, method)
    return os.path.isfile(path)


def list_completed_methods(base_dir, dataset_uuid):
    """Return a list of methods whose mapping output file exists."""
    completed = []
    for method in ALL_METHODS:
        if check_mapping_completed(base_dir, dataset_uuid, method):
            completed.append(method)
    return completed
