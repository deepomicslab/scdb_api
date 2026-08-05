import os
import glob
import json
import scanpy as sc
import pandas as pd
from collections import OrderedDict
from dataset.models import Dataset


# commot *_LR.h5ad 句柄缓存：mtime 感知 + LRU 上限 2 个文件。
# sc.read() 全量读 337MB ~3.1s；backed 只读 obsm 局部 ~1s；
# 缓存命中后 LRPairs / 信号强度 ~0.01s（重跑覆盖文件自动失效）。
_commot_adata_cache = OrderedDict()
_COMMOT_ADATA_CACHE_MAX = 2


def _load_commot_adata(file_path):
    """backed 打开 *_LR.h5ad（mtime 感知缓存）。返回 AnnData 或 None。"""
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

    def _get_commot_result_dir(self, dataset_name, mapping_method=None):
        if getattr(self, '_is_demo', False):
            demo_dir = os.path.join(self.path, 'result', 'commot')
            if os.path.isdir(demo_dir):
                return demo_dir
        try:
            from dataset.models import Dataset
            ds = Dataset.objects.get(dataset_id=dataset_name)
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
            print(f"[commot] Dataset lookup failed: {e}")
        return None

    def _find_commot_file(self, result_dir, pattern='*_LR.h5ad'):
        import glob
        if not result_dir or not os.path.isdir(result_dir):
            return None
        files = glob.glob(os.path.join(result_dir, pattern))
        return files[0] if files else None

    def getLRPairs(self, dataset, mapping_method=None):
        result_dir = self._get_commot_result_dir(dataset, mapping_method)
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

    def getReceivedSignalStrength(self, dataset, lr_pair, mapping_method=None):
        result_dir = self._get_commot_result_dir(dataset, mapping_method)
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
        }, index=adata.obs_names)  # 显式用 barcode 作 key，与 countHeatmap CSV 第一列一致
        res = {'receiver_strength': df.to_dict(orient='index'), 'status': 'success'}
        return res
    
    def getNetworkData(self, dataset, type, mapping_method=None):
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
