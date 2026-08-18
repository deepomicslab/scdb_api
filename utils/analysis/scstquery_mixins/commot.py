import os
import glob
import json
import scanpy as sc
import pandas as pd
from collections import OrderedDict
from dataset.models import Dataset
from utils.logging import get_logger

logger = get_logger('mixin_commot')


# commot *_LR.h5ad handle cache: mtime-aware + LRU capped at 2 files.
# sc.read() fully loads 337MB in ~3.1s; backed mode only reads the obsm slice in ~1s;
# after a cache hit, LRPairs / signal strength take ~0.01s (overwritten files
# are invalidated automatically).
_commot_adata_cache = OrderedDict()
_COMMOT_ADATA_CACHE_MAX = 2


def _load_commot_adata(file_path):
    """Open *_LR.h5ad in backed mode (mtime-aware cache). Returns AnnData or None."""
    if not os.path.exists(file_path):
        return None
    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        return None
    cached = _commot_adata_cache.get(file_path)
    if cached and cached[0] == mtime:
        _commot_adata_cache.move_to_end(file_path)
        return cached[1]
    adata = sc.read_h5ad(file_path, backed='r')
    _commot_adata_cache[file_path] = (mtime, adata)
    _commot_adata_cache.move_to_end(file_path)
    while len(_commot_adata_cache) > _COMMOT_ADATA_CACHE_MAX:
        _commot_adata_cache.popitem(last=False)
    return adata


class CommotMixin:
    """Commot cell-cell interaction result methods for Scstquery."""

    def _get_commot_result_dir(self, dataset_name, mapping_method=None, input_source=None):
        if getattr(self, '_is_demo', False):
            demo_dir = os.path.join(self.path, 'result', 'commot')
            if os.path.isdir(demo_dir):
                return demo_dir
        try:
            from dataset.models import Dataset
            ds = Dataset.objects.get(dataset_id=dataset_name)
            if input_source == 'st':
                if ds.precomputed_commot_path:
                    return ds.precomputed_commot_path
                return None
            uuid = ds.title
            base = os.path.join(self.path, f'dataset_{uuid}', 'subtask_commot', 'result')
            if mapping_method:
                new_dir = os.path.join(base, 'sc_st_mapping', mapping_method)
                if os.path.isdir(new_dir):
                    return new_dir
            if os.path.isdir(base):
                return base
            return None
        except Exception as e:
           logger.warning('[commot] Dataset lookup failed: %s', e)
        return None

    def _find_commot_file(self, result_dir, pattern='*_LR.h5ad'):
        import glob
        if not result_dir or not os.path.isdir(result_dir):
            return None
        files = glob.glob(os.path.join(result_dir, pattern))
        return files[0] if files else None

    def getLRPairs(self, dataset, mapping_method=None, input_source=None):
        result_dir = self._get_commot_result_dir(dataset, mapping_method, input_source)
        file_path = self._find_commot_file(result_dir, '*_LR.h5ad')
        if not file_path:
            return {'LR_pairs': [], 'status': 'error', 'message': f'Commot result not found for {dataset}'}
        if not os.path.exists(file_path):
            return {'LR_pairs': [], 'status': 'error', 'message': f'File not found: {file_path}'}
        adata = _load_commot_adata(file_path)
        if adata is None:
            return {'LR_pairs': [], 'status': 'error', 'message': f'File not found: {file_path}'}
        lr_pairs = adata.obsm['commot-cellchat-sum-receiver'].columns
        res = {'LR_pairs': lr_pairs.tolist(), 'status': 'success'}
        return res

    def getReceivedSignalStrength(self, dataset, lr_pair, mapping_method=None, input_source=None):
        result_dir = self._get_commot_result_dir(dataset, mapping_method, input_source)
        file_path = self._find_commot_file(result_dir, '*_LR.h5ad')
        if not file_path:
            return {'receiver_strength': {}, 'status': 'error', 'message': f'Commot result not found for {dataset}'}
        if not os.path.exists(file_path):
            return {'receiver_strength': {}, 'status': 'error', 'message': f'File not found: {file_path}'}
        adata = _load_commot_adata(file_path)
        if adata is None:
            return {'receiver_strength': {}, 'status': 'error', 'message': f'File not found: {file_path}'}
        spatial_coords = adata.obsm['spatial']
        receiver_strength = adata.obsm['commot-cellchat-sum-receiver'][lr_pair]
        
        df = pd.DataFrame({
            'x': spatial_coords[:, 0],
            'y': spatial_coords[:, 1],
            lr_pair: receiver_strength
        }, index=adata.obs_names)  # use the barcode explicitly as the key, consistent with the first column of the countHeatmap CSV
        res = {'receiver_strength': df.to_dict(orient='index'), 'status': 'success'}
        return res
    
    def getNetworkData(self, dataset, type, mapping_method=None, input_source=None):
        if input_source == 'st':
            try:
                from dataset.models import Dataset
                ds = Dataset.objects.get(dataset_id=dataset)
                base = ds.precomputed_cellchat_path
            except Dataset.DoesNotExist:
                return {'network_data': {}, 'status': 'error', 'message': f'File not found: {dataset}'}
            if not base:
                return {'network_data': {}, 'status': 'error', 'message': f'File not found: {dataset}'}
            method_base = base
        else:
            base = os.path.join(self.path, f"dataset_{dataset}", "subtask_cellchat", "result")
            if mapping_method:
                method_base = os.path.join(base, "sc_st_mapping", mapping_method)
            else:
                method_base = base
        if type == 'weight':
            file_path = os.path.join(method_base, "cellchat/network/result_data_weight.json")
        elif type == 'count':
            file_path = os.path.join(method_base, "cellchat/network/result_data_count.json")
        else:
            return {'network_data': {}, 'status': 'error', 'message': f'Unknown type: {type}'}

        if not os.path.exists(file_path):
            return {'network_data': {}, 'status': 'error', 'message': f'File not found: {file_path}'}

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        res = {'network_data': data, 'status': 'success'}
        return res
