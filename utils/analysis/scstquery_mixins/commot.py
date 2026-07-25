import os
import glob
import json
import scanpy as sc
import pandas as pd
from dataset.models import Dataset


class CommotMixin:
    """Commot cell-cell interaction result methods for Scstquery."""

    def _get_commot_result_dir(self, dataset_name, mapping_method=None):
        print(f"[commot] looking up dataset: {dataset_name}")
        if getattr(self, '_is_demo', False):
            demo_dir = os.path.join(self.path, 'result', 'commot')
            if os.path.isdir(demo_dir):
                return demo_dir
        try:
            from dataset.models import Dataset
            ds = Dataset.objects.get(dataset_id=dataset_name)
            uuid = ds.title
            base = os.path.join(self.path, f'dataset_{uuid}', 'subtask_commot', 'result')
            print(f"[commot] result_dir base: {base}")
            if mapping_method:
                new_dir = os.path.join(base, 'sc_st_mapping', mapping_method)
                if os.path.isdir(new_dir):
                    print(f"[commot] using method dir: {new_dir}")
                    return new_dir
            if os.path.isdir(base):
                print(f"[commot] using flat dir: {base}")
                return base
            return None
        except Exception as e:
            print(f"[commot] Dataset lookup failed: {e}")
        return None

    def _find_commot_file(self, result_dir, pattern='*_LR.h5ad'):
        import glob
        if not result_dir or not os.path.isdir(result_dir):
            print(f"[commot] result_dir not found: {result_dir}")
            return None
        files = glob.glob(os.path.join(result_dir, pattern))
        print(f"[commot] found {len(files)} files: {[os.path.basename(f) for f in files]}")
        return files[0] if files else None

    def getLRPairs(self, dataset, mapping_method=None):
        result_dir = self._get_commot_result_dir(dataset, mapping_method)
        file_path = self._find_commot_file(result_dir, '*_LR.h5ad')
        if not file_path:
            return {'LR_pairs': [], 'status': 'error', 'message': f'Commot result not found for {dataset}'}
        if not os.path.exists(file_path):
            return {'LR_pairs': [], 'status': 'error', 'message': f'File not found: {file_path}'}
        adata = sc.read(file_path)
        lr_pairs = adata.obsm['commot-cellchat-sum-receiver'].columns
        print('lr_pairs', lr_pairs)
        res = {'LR_pairs': lr_pairs.tolist(), 'status': 'success'}
        return res

    def getReceivedSignalStrength(self, dataset, lr_pair, mapping_method=None):
        result_dir = self._get_commot_result_dir(dataset, mapping_method)
        file_path = self._find_commot_file(result_dir, '*_LR.h5ad')
        if not file_path:
            return {'receiver_strength': {}, 'status': 'error', 'message': f'Commot result not found for {dataset}'}
        if not os.path.exists(file_path):
            return {'receiver_strength': {}, 'status': 'error', 'message': f'File not found: {file_path}'}
        adata = sc.read(file_path)
        spatial_coords = adata.obsm['spatial']
        receiver_strength = adata.obsm['commot-cellchat-sum-receiver'][lr_pair]
        
        df = pd.DataFrame({
            'x': spatial_coords[:, 0],
            'y': spatial_coords[:, 1],
            lr_pair: receiver_strength
        })
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
