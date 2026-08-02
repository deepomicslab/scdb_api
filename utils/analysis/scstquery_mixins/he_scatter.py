import os
import json
import time
import numpy as np
import pandas as pd
from dataset.models import Dataset
from utils.spatial_calibration import read_spatial_calibration


# 散点数据缓存：key = CSV 绝对路径，mtime 校验（重跑覆盖文件即自动失效）。
# 命中跳过 read_csv + to_dict + distribution json + 校准 DB 查询，仅剩 DRF 序列化。
_he_scatter_cache = {}
_HE_SCATTER_CACHE_TTL = 3600


def _load_he_scatter(result_path, dist_path, dataset_id):
    """读取 HE 散点数据（CSV + cluster_celltype_distribution + 校准值），带 mtime 感知缓存。"""
    try:
        csv_mtime = os.path.getmtime(result_path)
        dist_mtime = os.path.getmtime(dist_path) if os.path.exists(dist_path) else None
    except OSError:
        return {'status': 'fail', 'message': f'HE scatter data not found: {result_path}'}

    cached = _he_scatter_cache.get(result_path)
    if cached and cached[1] == csv_mtime and cached[2] == dist_mtime and time.time() < cached[3]:
        return cached[0]

    query_count_result = pd.read_csv(result_path, index_col=0)
    if 'clusters' in query_count_result.columns:
        query_count_result = query_count_result.drop(columns=['clusters'])
    query_count_result['Label'] = query_count_result['Label'].astype(str)
    query_count_result = query_count_result.replace({np.nan: None})

    cluster_celltype_distribution_data = {}
    if dist_path and os.path.exists(dist_path):
        with open(dist_path, 'r') as json_file:
            cluster_celltype_distribution_data = json.load(json_file)

    scalef, spot = read_spatial_calibration(dataset_id)
    res = {
        'scatter': query_count_result.to_dict(orient='index'),
        'cluster_celltype_distribution': cluster_celltype_distribution_data,
        'status': 'success',
        'tissue_hires_scalef': scalef,
        'spot_diameter_fullres': spot,
    }
    _he_scatter_cache[result_path] = (res, csv_mtime, dist_mtime, time.time() + _HE_SCATTER_CACHE_TTL)
    return res


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
        dist_path = os.path.join(self.path, "result/he/cluster_celltype_distribution.json")
        return result_path, dist_path

    def getHEScatterresult(self, result):
        result_path, dist_path = self._he_result_paths(result, 'he_scatter')
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE scatter data not found: {result_path}'}
        res = _load_he_scatter(result_path, dist_path, result)
        if res.get('status') != 'fail':
            res = {k: res[k] for k in ('scatter', 'cluster_celltype_distribution', 'status',
                                       'tissue_hires_scalef', 'spot_diameter_fullres')}
        return res

    def getQueryCountHeatmapResult(self, dataset):
        result_path, dist_path = self._he_result_paths(dataset, 'hierarchical_clustering')
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE query count data not found: {result_path}'}
        res = _load_he_scatter(result_path, dist_path, dataset)
        if res.get('status') != 'fail':
            res = {k: res[k] for k in ('scatter', 'status',
                                       'tissue_hires_scalef', 'spot_diameter_fullres')}
        return res
