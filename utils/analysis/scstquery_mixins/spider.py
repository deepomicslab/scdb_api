import os
import numpy as np
import pandas as pd
import scanpy as sc
from scipy import sparse
from dataset.models import Dataset
from utils.spatial_calibration import read_spatial_calibration
from scdb_api import settings_local as local_settings


class SpiderMixin:
    """SPIDER spatial interaction result methods for Scstquery."""

    def _find_spider_h5ad(self, dataset_id, mapping_method=None):
        if dataset_id:
            try:
                ds = Dataset.objects.get(dataset_id=dataset_id)
                uuid = ds.title
                base = os.path.join(self.path, f'dataset_{uuid}', 'subtask_spider', 'result')
                if mapping_method:
                    new_path = os.path.join(base, 'sc_st_mapping', mapping_method, 'adata_spider.h5ad')
                    if os.path.exists(new_path):
                        return new_path
                old_path = os.path.join(base, 'adata_spider.h5ad')
                if os.path.exists(old_path):
                    return old_path
            except Dataset.DoesNotExist:
                pass
        return os.path.join(self.path, 'result/spider/adata_spider.h5ad')

    def _resolve_dataset_uuid(self, dataset_id):
        if not dataset_id:
            return None
        try:
            return Dataset.objects.get(dataset_id=dataset_id).title
        except Dataset.DoesNotExist:
            return None

    def getLRSpearmanData(self, dataset=None, mapping_method=None):
        """
        Read LR-level Spearman correlation CSVs.
        Priority:
          1. subtask_lr_comparison/result/ (new pipeline)
          2. subtask_spider/result/ (legacy/demo)
        """
        uuid = self._resolve_dataset_uuid(dataset)
        base_dir = os.path.join(self.path, f'dataset_{uuid}') if uuid else self.path

        # 优先级1: lr_comparison 目录
        lr_base = os.path.join(base_dir, 'subtask_lr_comparison', 'result')
        sc_path = os.path.join(lr_base, 'spearman', 'lr_level_spearman_correlation_sc.csv')
        if mapping_method:
            st_path = os.path.join(lr_base, 'sc_st_mapping', mapping_method, 'spearman', 'lr_level_spearman_correlation_sc_st.csv')
        else:
            st_path = os.path.join(lr_base, 'spearman', 'lr_level_spearman_correlation_sc_st.csv')

        if os.path.exists(sc_path) and os.path.exists(st_path):
            return self._read_spearman_csvs(sc_path, st_path)

        # 优先级2: 旧 spider 目录 (sc_st_mapping/{method}/spearman/)
        spider_base = os.path.join(base_dir, 'subtask_spider', 'result')
        if mapping_method:
            method_dir = os.path.join(spider_base, 'sc_st_mapping', mapping_method)
            method_sc_path = os.path.join(method_dir, 'spearman', 'lr_level_spearman_correlation_sc.csv')
            method_sc_st_path = os.path.join(method_dir, 'spearman', 'lr_level_spearman_correlation_sc_st.csv')
            if os.path.exists(method_sc_st_path):
                return self._read_spearman_csvs(method_sc_path, method_sc_st_path)

        # 优先级3: 旧 spider 目录 (spearman/ 平级)
        fallback_sc = os.path.join(spider_base, 'spearman', 'lr_level_spearman_correlation_sc.csv')
        fallback_st = os.path.join(spider_base, 'spearman', 'lr_level_spearman_correlation_sc_st.csv')
        if os.path.exists(fallback_sc) or os.path.exists(fallback_st):
            return self._read_spearman_csvs(fallback_sc, fallback_st)

        # 优先级4: demo 路径
        demo_base = os.path.join(self.path, 'result', 'spider')
        demo_sc = os.path.join(demo_base, 'spearman', 'lr_level_spearman_correlation_sc.csv')
        demo_st = os.path.join(demo_base, 'spearman', 'lr_level_spearman_correlation_sc_st.csv')
        return self._read_spearman_csvs(demo_sc, demo_st)

    def _read_spearman_csvs(self, sc_path, st_path):
        results = []

        def clean_val(val, default_val):
            try:
                if pd.isna(val): return default_val
                if isinstance(val, (int, float)) and np.isinf(val): return default_val
                return float(val)
            except:
                return default_val

        def clean_int(val, default_val=0):
            try:
                if pd.isna(val): return default_val
                return int(val)
            except:
                return default_val

        try:
            # SC
            if os.path.exists(sc_path):
                df_sc = pd.read_csv(sc_path)
                for _, row in df_sc.iterrows():
                    results.append({
                        "id": str(row.get('lr_pair', 'unknown')),
                        "type": "SC",
                        "spearman_rho": clean_val(row.get('spearman_rho'), 0),
                        "spearman_pval": clean_val(row.get('spearman_pval'), 1.0),
                        "n_receivers": clean_int(row.get('n_receivers'), 0),
                        "mean_activity": clean_val(row.get('mean_activity'), 0),
                        "mean_max_ccc": clean_val(row.get('mean_max_ccc'), 0)
                    })

            # SC + ST
            if os.path.exists(st_path):
                df_scst = pd.read_csv(st_path)
                for _, row in df_scst.iterrows():
                    results.append({
                        "id": str(row.get('lr_pair', 'unknown')),
                        "type": "SC + ST",
                        "spearman_rho": clean_val(row.get('spearman_rho'), 0),
                        "spearman_pval": clean_val(row.get('spearman_pval'), 1.0),
                        "n_receivers": clean_int(row.get('n_receivers'), 0),
                        "mean_activity": clean_val(row.get('mean_activity'), 0),
                        "mean_max_ccc": clean_val(row.get('mean_max_ccc'), 0)
                    })

            return {'data': results, 'status': 'success'}

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'data': [], 'status': 'error', 'message': str(e)}

    def getSpiderInit(self, dataset=None, mapping_method=None):
        h5ad_path = self._find_spider_h5ad(dataset, mapping_method)
        if not os.path.exists(h5ad_path):
            return {'data': {}, 'status': 'error', 'message': f'File not found: {h5ad_path}'}
        try:
            adata = sc.read_h5ad(h5ad_path, backed='r')
            metadata = []
            if 'pattern_score' in adata.obsm.keys():
                n_patterns = adata.obsm['pattern_score'].shape[1]
                for i in range(n_patterns):
                    pattern_item = {"id": i, "name": f"Pattern {i}", "svis": []}
                    if 'label' in adata.var.columns:
                        pattern_vars = adata.var[adata.var['label'] == i]
                        corr_col = f'pattern_correlation_{i}'
                        if corr_col in pattern_vars.columns:
                            pattern_vars = pattern_vars.sort_values(by=corr_col, ascending=False)
                        top_vars = pattern_vars.head(10)
                        for lr_name, row in top_vars.iterrows():
                            score = row.get(corr_col, 0)
                            pattern_item['svis'].append({"name": lr_name, "score": round(float(score), 3)})
                    metadata.append(pattern_item)
            coordinates = []
            scalef, spot = read_spatial_calibration(dataset)
            if 'spatial' in adata.obsm.keys():
                coords = adata.obsm['spatial']
                obs_names = adata.obs_names
                if hasattr(coords, 'to_numpy'):
                    coords = coords.to_numpy()
                coordinates = [{"id": name, "x": float(coords[i][0]) * (scalef or 1.0), "y": float(coords[i][1]) * (scalef or 1.0)} for i, name in enumerate(obs_names)]
            elif 'row' in adata.obs.columns and 'col' in adata.obs.columns:
                rows = adata.obs['row'].values
                cols = adata.obs['col'].values
                obs_names = adata.obs_names
                coordinates = [{"id": name, "x": float(r), "y": float(c)} for name, r, c in zip(obs_names, rows, cols)]
            return {'data': {'metadata': metadata, 'coordinates': coordinates, 'tissue_hires_scalef': scalef, 'spot_diameter_fullres': spot}, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getSpiderPatternData(self, dataset=None, pattern_id=None, mapping_method=None):
        h5ad_path = self._find_spider_h5ad(dataset, mapping_method)
        try:
            if pattern_id is None:
                raise ValueError("Pattern ID is required")
            pid = int(pattern_id)
            adata = sc.read_h5ad(h5ad_path, backed='r')
            if 'pattern_score' not in adata.obsm.keys():
                raise ValueError("pattern_score not found in data")
            scores = adata.obsm['pattern_score'][:, pid]
            return {'data': scores.flatten().tolist(), 'status': 'success'}
        except Exception as e:
            return {'data': [], 'status': 'error', 'message': str(e)}

    def getSpiderLRData(self, dataset=None, lr_name=None, mapping_method=None):
        h5ad_path = self._find_spider_h5ad(dataset, mapping_method)
        try:
            if not lr_name:
                raise ValueError("LR Name is required")
            adata = sc.read_h5ad(h5ad_path, backed='r')
            if lr_name not in adata.var_names:
                return {'data': [], 'status': 'error', 'message': f'LR pair {lr_name} not found'}
            data_col = adata[:, lr_name].X
            if sparse.issparse(data_col):
                values = data_col.toarray().flatten()
            else:
                values = data_col.flatten()
            return {'data': values.tolist(), 'status': 'success'}
        except Exception as e:
            return {'data': [], 'status': 'error', 'message': str(e)}
