import os
import json
import time
import numpy as np
import pandas as pd
from dataset.models import Dataset
from utils.spatial_calibration import read_spatial_calibration


# Scatter data cache: key = absolute CSV path, mtime-checked (re-running overwrites
# the file, which invalidates the entry automatically).
# On a hit, read_csv + to_dict + the calibration DB query are skipped; only DRF
# serialization remains.
_he_scatter_cache = {}
_HE_SCATTER_CACHE_TTL = 3600


def _load_he_scatter(result_path, dataset_id):
    """Read the HE scatter data (CSV + calibration values) with an mtime-aware cache. Does not include distribution (separate endpoint)."""
    try:
        csv_mtime = os.path.getmtime(result_path)
    except OSError:
        return {'status': 'fail', 'message': f'HE scatter data not found: {result_path}'}

    cached = _he_scatter_cache.get(result_path)
    if cached and cached[1] == csv_mtime and time.time() < cached[2]:
        return cached[0]

    query_count_result = pd.read_csv(result_path, index_col=0)
    if 'clusters' in query_count_result.columns:
        query_count_result = query_count_result.drop(columns=['clusters'])
    query_count_result['Label'] = query_count_result['Label'].astype(str)
    query_count_result = query_count_result.replace({np.nan: None})

    scalef, spot = read_spatial_calibration(dataset_id)
    res = {
        'scatter': query_count_result.to_dict(orient='index'),
        'status': 'success',
        'tissue_hires_scalef': scalef,
        'spot_diameter_fullres': spot,
    }
    _he_scatter_cache[result_path] = (res, csv_mtime, time.time() + _HE_SCATTER_CACHE_TTL)
    return res


# cluster_celltype_distribution.json cache: mtime-aware.
# This JSON is only used for the pie chart that pops up when clicking a scatter
# point; it is a separate endpoint fetched on demand/in parallel, not bundled
# into the first-screen scatter response.
_he_distribution_cache = {}
_HE_DISTRIBUTION_CACHE_TTL = 3600


def _load_he_distribution(dist_path):
    """Read cluster_celltype_distribution.json (mtime-aware cache)."""
    if not os.path.exists(dist_path):
        return {}
    try:
        mtime = os.path.getmtime(dist_path)
    except OSError:
        return {}
    cached = _he_distribution_cache.get(dist_path)
    if cached and cached[1] == mtime and time.time() < cached[2]:
        return cached[0]
    with open(dist_path, 'r') as json_file:
        data = json.load(json_file)
    _he_distribution_cache[dist_path] = (data, mtime, time.time() + _HE_DISTRIBUTION_CACHE_TTL)
    return data


class HEScatterMixin:
    """HE scatter and query count heatmap result methods for Scstquery."""

    def _resolve_subtask_he_path(self, dataset_id, subtask_type='hierarchical_clustering'):
        if not dataset_id:
            return None
        try:
            ds = Dataset.objects.get(dataset_id=dataset_id)
            uuid = ds.title
            he_dir = os.path.join(self.path, f'dataset_{uuid}', f'subtask_{subtask_type}', 'result', 'he')
            if os.path.isdir(he_dir):
                return he_dir
        except Dataset.DoesNotExist:
            pass
        return None

    def _he_result_paths(self, dataset_id, subtask_type='he_scatter'):
        subtask_he = self._resolve_subtask_he_path(dataset_id, subtask_type)
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        result_path = os.path.join(base, "all_merged_data_with_labels.csv")
        return result_path

    def _he_dist_path(self):
        return os.path.join(self.path, "result/he/cluster_celltype_distribution.json")

    def getHEScatterresult(self, result):
        result_path = self._he_result_paths(result, 'he_scatter')
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE scatter data not found: {result_path}'}
        res = _load_he_scatter(result_path, result)
        if res.get('status') != 'fail':
            res = {k: res[k] for k in ('scatter', 'status',
                                       'tissue_hires_scalef', 'spot_diameter_fullres')}
        return res

    def getHEClusterDistribution(self, dataset):
        """cluster_celltype_distribution (for the pie chart on scatter point click); separate endpoint so the frontend can fetch it in parallel."""
        dist_path = self._he_dist_path()
        data = _load_he_distribution(dist_path)
        return {'cluster_celltype_distribution': data, 'status': 'success'}

    def getQueryCountHeatmapResult(self, dataset):
        result_path = self._he_result_paths(dataset, 'hierarchical_clustering')
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE query count data not found: {result_path}'}
        res = _load_he_scatter(result_path, dataset)
        if res.get('status') != 'fail':
            res = {k: res[k] for k in ('scatter', 'status',
                                       'tissue_hires_scalef', 'spot_diameter_fullres')}
        return res
