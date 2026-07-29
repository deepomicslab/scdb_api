import os
import pickle
import pandas as pd
from dataset.models import Dataset


class AlphaTalkMixin:
    """AlphaTalk cell-cell interaction result methods for Scstquery."""

    def _find_alphatalk_pkl(self, dataset=None):
        if getattr(self, '_is_demo', False):
            return os.path.join(self.path, 'result/alphatalk/cci_result.pkl')
        if not dataset:
            return None
        try:
            db_obj = Dataset.objects.get(dataset_id=dataset)
        except Dataset.DoesNotExist:
            return None
        base = os.path.join(self.path, f'dataset_{db_obj.title}', 'subtask_alphatalk', 'result')
        return os.path.join(base, 'alphatalk', 'cci_result.pkl')

    def getAlphaTalkLRPairs(self, page=1, pageSize=15, 
                            sender=None, receiver=None, ligand=None, receptor=None, type_col=None,
                            min_score=None, max_score=None,
                            min_lr_score=None, max_lr_score=None,
                            min_p_value=None, max_p_value=None,
                            sortBy=None, order=None, get_metadata=None, dataset=None):
        
        pkl_path = self._find_alphatalk_pkl(dataset)

        try:
            if not os.path.exists(pkl_path):
                return {'data': [], 'total': 0, 'status': 'error', 'message': "File not found"}

            with open(pkl_path, 'rb') as f:
                result_obj = pickle.load(f)

            if 'lr_score' not in result_obj:
                return {'data': [], 'total': 0, 'status': 'error', 'message': "Invalid data format"}
            
            df = result_obj['lr_score']

            if df.empty:
                return {'data': [], 'total': 0, 'status': 'success', 'message': "Empty result"}

            # 1. 类别筛选
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

            # 2. 数值范围筛选
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
                    df_page[col] = df_page[col].apply(lambda x: round(float(x), 4) if x is not None else 0)

            return {
                'data': df_page.to_dict(orient='records'),
                'total': total_count,
                'status': 'success'
            }

        except Exception as e:
            return {'data': [], 'total': 0, 'status': 'error', 'message': str(e)}
