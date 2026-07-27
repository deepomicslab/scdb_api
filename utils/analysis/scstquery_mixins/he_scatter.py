import os
import json
import numpy as np
import pandas as pd
from dataset.models import Dataset
from utils.spatial_calibration import read_spatial_calibration


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

    def getHEScatterresult(self, result):
        subtask_he = self._resolve_subtask_he_path(result, 'he_scatter')
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        result_path = os.path.join(base, "all_merged_data_with_labels.csv")
        cluster_celltype_distribution_filepath = os.path.join(self.path, "result/he/cluster_celltype_distribution.json")
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE scatter data not found: {result_path}'}
        query_count_result = pd.read_csv(result_path, index_col=0)
        if 'clusters' in query_count_result.columns:
            query_count_result = query_count_result.drop(columns=['clusters'])
        query_count_result['Label'] = query_count_result['Label'].astype(str)
        query_count_result = query_count_result.replace({np.nan: None})
        cluster_celltype_distribution_data = {}
        if os.path.exists(cluster_celltype_distribution_filepath):
            with open(cluster_celltype_distribution_filepath, 'r') as json_file:
                cluster_celltype_distribution_data = json.load(json_file)
        scalef, spot = read_spatial_calibration(result)
        res = {'scatter': query_count_result.to_dict(orient='index'), 'cluster_celltype_distribution': cluster_celltype_distribution_data, 'status': 'success', 'tissue_hires_scalef': scalef, 'spot_diameter_fullres': spot}
        return res
    
    def getQueryCountHeatmapResult(self, dataset):
        subtask_he = self._resolve_subtask_he_path(dataset)
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        result_path = os.path.join(base, 'all_merged_data_with_labels.csv')
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE query count data not found: {result_path}'}
        query_count_result = pd.read_csv(result_path, index_col=0)
        if 'clusters' in query_count_result.columns:
            query_count_result = query_count_result.drop(columns=['clusters'])
        query_count_result['Label'] = query_count_result['Label'].astype(str)
        query_count_result = query_count_result.replace({np.nan: None})
        scalef, spot = read_spatial_calibration(dataset)
        res = {'scatter': query_count_result.to_dict(orient='index'), 'status': 'success', 'tissue_hires_scalef': scalef, 'spot_diameter_fullres': spot}
        return res
