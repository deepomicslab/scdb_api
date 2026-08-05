import os
import pickle
import pandas as pd
from collections import OrderedDict
from dataset.models import Dataset


# cci_result.pkl parse cache: mtime-aware + LRU capped at 2 files.
# pickle.load fully reads 4.9MB in ~0.3s; on a hit, filtering/sorting/pagination/
# metadata all run on the in-memory df (~ms).
# Re-runs overwriting the pkl invalidate the entry automatically. The cached df is
# read-only (filtering/sorting return new objects, never mutate in place).
_alphatalk_df_cache = OrderedDict()
_ALPHATALK_CACHE_MAX = 2


def _load_alphatalk_df(pkl_path):
    """Read the lr_score DataFrame from cci_result.pkl (mtime-aware cache)."""
    try:
        mtime = os.path.getmtime(pkl_path)
    except OSError:
        return None
    cached = _alphatalk_df_cache.get(pkl_path)
    if cached and cached[0] == mtime:
        _alphatalk_df_cache.move_to_end(pkl_path)
        return cached[1]
    with open(pkl_path, 'rb') as f:
        result_obj = pickle.load(f)
    if 'lr_score' not in result_obj:
        return None
    df = result_obj['lr_score']
    _alphatalk_df_cache[pkl_path] = (mtime, df)
    _alphatalk_df_cache.move_to_end(pkl_path)
    while len(_alphatalk_df_cache) > _ALPHATALK_CACHE_MAX:
        _alphatalk_df_cache.popitem(last=False)
    return df


class AlphaTalkMixin:
    """AlphaTalk cell-cell interaction result methods for Scstquery."""

    def _get_alphatalk_result_dir(self, dataset_id=None, mapping_method=None):
        if getattr(self, '_is_demo', False):
            return os.path.join(self.path, 'result/alphatalk', 'cci_result.pkl')
        if dataset_id:
            try:
                ds = Dataset.objects.get(dataset_id=dataset_id)
                uuid = ds.title
                base = os.path.join(self.path, f'dataset_{uuid}', 'subtask_alphatalk', 'result')
                if mapping_method:
                    pkl_path = os.path.join(base, 'sc_st_mapping', mapping_method, 'cci_result.pkl')
                    if os.path.exists(pkl_path):
                        return pkl_path
                flat_path = os.path.join(base, 'cci_result.pkl')
                if os.path.exists(flat_path):
                    return flat_path
            except Dataset.DoesNotExist:
                pass
        return os.path.join(self.path, 'result/alphatalk/cci_result.pkl')

    def getAlphaTalkLRPairs(self, page=1, pageSize=15, 
                            sender=None, receiver=None, ligand=None, receptor=None, type_col=None,
                            min_score=None, max_score=None,
                            min_lr_score=None, max_lr_score=None,
                            min_p_value=None, max_p_value=None,
                            sortBy=None, order=None, get_metadata=None,
                            dataset=None, mapping_method=None):
        
        pkl_path = self._get_alphatalk_result_dir(dataset, mapping_method)

        try:
            if not os.path.exists(pkl_path):
                return {'data': [], 'total': 0, 'status': 'error', 'message': "File not found"}

            df = _load_alphatalk_df(pkl_path)

            if df is None:
                return {'data': [], 'total': 0, 'status': 'error', 'message': "Invalid data format"}

            if df.empty:
                return {'data': [], 'total': 0, 'status': 'success', 'message': "Empty result"}

            # 1. Categorical filters
            if sender:
                df = df[df['cell_sender'] == sender]
            if receiver:
                df = df[df['cell_receiver'] == receiver]
            if ligand:
                df = df[df['ligand'] == ligand]
            if receptor:
                df = df[df['receptor'] == receptor]
            if type_col:
                df = df[df['type'] == type_col]

            # 2. Numeric range filters
            def filter_range(dataframe, col_name, min_v, max_v):
                if col_name not in dataframe.columns: return dataframe
                temp_df = dataframe
                if min_v is not None and str(min_v).strip() != '':
                    try: temp_df = temp_df[temp_df[col_name] >= float(min_v)]
                    except: pass
                if max_v is not None and str(max_v).strip() != '':
                    try: temp_df = temp_df[temp_df[col_name] <= float(max_v)]
                    except: pass
                return temp_df

            df = filter_range(df, 'score', min_score, max_score)
            df = filter_range(df, 'lr_score', min_lr_score, max_lr_score)
            df = filter_range(df, 'co_exp_p', min_p_value, max_p_value)

            if get_metadata == 'true':
                return {
                    'status': 'success',
                    'data': {
                        'senders': sorted(df['cell_sender'].astype(str).unique().tolist()),
                        'receivers': sorted(df['cell_receiver'].astype(str).unique().tolist()),
                        'ligands': sorted(df['ligand'].astype(str).unique().tolist()),
                        'receptors': sorted(df['receptor'].astype(str).unique().tolist()),
                        'types': sorted(df['type'].astype(str).unique().tolist())
                    }
                }

            if sortBy and order and order in ['ascend', 'descend']:
                if sortBy in df.columns:
                    is_ascending = True if order == 'ascend' else False
                    df = df.sort_values(by=sortBy, ascending=is_ascending)

            total_count = len(df)
            try:
                page = int(page)
                pageSize = int(pageSize)
            except ValueError:
                page = 1
                pageSize = 15
            
            if total_count > 0 and (page - 1) * pageSize >= total_count:
                page = 1 
            
            start_idx = (page - 1) * pageSize
            end_idx = start_idx + pageSize
            
            df_page = df.iloc[start_idx:end_idx].copy()

            df_page = df_page.where(pd.notnull(df_page), None)
            numeric_cols = ['score', 'lr_score', 'rt_score', 'co_exp_p', 'co_exp_value']
            for col in numeric_cols:
                if col in df_page.columns:
                    df_page[col] = df_page[col].apply(lambda x: x if x is None else round(float(x), 4))

            return {
                'data': df_page.to_dict(orient='records'),
                'total': total_count,
                'status': 'success'
            }

        except Exception as e:
            return {'data': [], 'total': 0, 'status': 'error', 'message': str(e)}