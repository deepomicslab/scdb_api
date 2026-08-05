import os
import json
import pandas as pd
import scanpy as sc
from pathlib import Path
from scdb_api import settings_local as local_settings
from utils.page import paginate_dataframe
from dataset.models import Dataset


class CommonMixin:
    """Common result methods for Scstquery: metadata, datasets, downloads, images."""

    def getOrgansAndDatasets(self):
        json_path = os.path.join(self.path, 'result/sc_query/result_scores.json')
        if not os.path.exists(json_path):
            return {
                'status': 'fail',
                'message': f"File '{json_path}' not found."
            }

        try:
            with open(json_path, 'r', encoding='utf-8') as json_file:
                raw_data = json.load(json_file)
        except Exception as e:
             return {'status': 'fail', 'message': str(e)}

        INTERACTION_TYPES = {'commot', 'cellchat', 'spider', 'scst_mapping', 'alphatalk', 'lr_comparison'}
        subtask_map = {}
        try:
            from task.models import SubTask, tasks as task_model
            main_task = task_model.objects.get(userpath=self.path.replace(local_settings.USERTASKPATH, ''))
            for st in SubTask.objects.filter(main_task=main_task).exclude(
                subtask_type='hierarchical_clustering'
            ).exclude(status='Created').order_by('-id'):
                dp = st.dataset_path
                if dp not in subtask_map:
                    subtask_map[dp] = {}
                params = st.parameters if isinstance(st.parameters, dict) else {}
                mapping_method = params.get('mapping_method', '')
                if mapping_method and st.subtask_type in INTERACTION_TYPES:
                    cache_key = f"{st.subtask_type}__{mapping_method}"
                else:
                    cache_key = st.subtask_type
                if cache_key not in subtask_map[dp]:
                    subtask_map[dp][cache_key] = {
                        'id': st.id,
                        'status': st.status.lower(),
                        'job_id': st.job_id,
                        'subtask_type': st.subtask_type,
                        'mapping_method': mapping_method or None,
                    }
        except Exception:
            pass

        transformed_data = {}

        for organ_name, datasets_dict in raw_data.items():
            transformed_data[organ_name] = {}
            
            for original_path, scores in datasets_dict.items():
                extracted_uuid = self._extract_dataset_uuid(original_path) or ""

                db_obj = None
                if extracted_uuid:
                    db_obj = Dataset.objects.filter(title=extracted_uuid).first()

                if db_obj:
                    new_key = db_obj.dataset_id
                    description = f"{db_obj.disease} | {db_obj.n_spots} spots | {db_obj.n_donors} donors"
                    meta_info = {
                        "dataset_id": db_obj.dataset_id,
                        "uuid": extracted_uuid,
                        "disease": db_obj.disease,
                        "n_spots": db_obj.n_spots,
                        "organ": db_obj.organ,
                    }
                else:
                    new_key = extracted_uuid if extracted_uuid else os.path.basename(original_path)
                    description = "Unknown Dataset"
                    meta_info = {"uuid": extracted_uuid}

                new_value = scores.copy()
                # 注意：不要把服务器路径（original_path / file_path）下发给前端，
                # 前端只使用 dataset_id；需要路径时由后端 resolve_marker_path 反查。
                new_value['title'] = new_key
                new_value['description'] = description
                new_value['meta'] = meta_info
                # 图像存在性（hires.jpg 缓存判定）：前端据此跳过 getImg 请求，避免无图 404 刷日志
                if db_obj:
                    new_value['has_image'] = db_obj.has_image()

                _subtasks = subtask_map.get(db_obj.dataset_id if db_obj else None, {}) \
                    or subtask_map.get(original_path, {})
                new_value['subtasks'] = _subtasks

                transformed_data[organ_name][new_key] = new_value

        return {
            'status': 'success',
            'data': transformed_data
        }
    
    def getDatasetInfo(self, dataset):
        from pathlib import Path
        from utils.analysis.base import resolve_marker_path

        # 前端只传 dataset_id，服务器路径由后端反查，绝不下发/接收客户端路径
        task_dir = self.path.replace(local_settings.USERTASKPATH, '')
        datasetPath = resolve_marker_path(task_dir, dataset)
        if not datasetPath or not os.path.exists(datasetPath):
            return {
                'status': 'fail',
                'message': f'Cannot resolve marker path for dataset {dataset}'
            }

        dataset_marker_df = pd.read_csv(datasetPath)
        num_rows_marker, num_columns_marker = dataset_marker_df.shape

        dataset_clusters_path = datasetPath.replace("_marker.csv", "_clusters.csv")
        dataset_clusters_df = pd.read_csv(dataset_clusters_path)
        num_rows_clusters, num_columns_clusters = dataset_clusters_df.shape

        old_path = Path(datasetPath)
        filtered_adata_path = old_path.parent.parent / "st_filtered_adata" / (old_path.stem.replace("_marker", "_filtered") + ".h5ad")

        filtered_adata = sc.read_h5ad(filtered_adata_path, backed='r')

        tissues = filtered_adata.obs['tissue'].unique().tolist() if 'tissue' in filtered_adata.obs.columns else []
        donors = filtered_adata.obs['donor_id'].unique().tolist() if 'donor_id' in filtered_adata.obs.columns else []

        dataset_info = {
            'num_celltypes_or_clusters': num_rows_marker,
            'num_marker_genes': num_columns_marker,
            'num_spots': num_rows_clusters,
            'num_tissues': len(tissues),
            'num_donors': len(donors)
        }

        return {
            'status': 'success',
            'data': dataset_info
        }

    def getmetaresult(self,page,pagesize):
        metadatafile = self.path + f'/result/meta/test_cluster_1_meta_data_addquerycell.txt'
        metadata = pd.read_csv(metadatafile,sep='\t', index_col=False)
        count = metadata.shape[0]
        metadata.rename(columns={metadata.columns[0]: 'Cell_id'}, inplace=True)
        metadata=paginate_dataframe(metadata, page, pagesize)
        res={'results': metadata.to_dict(orient='records'), 'count': count}
        return res

    def download(self, filename):
        if filename.endswith('.h5ad'):
            filepath = os.path.join(self.path, 'result/sc_query/annotation_h5ad', filename)
        elif filename.endswith('.txt'):
            filepath = os.path.join(self.path, 'result/meta', filename)
        elif filename.endswith('.csv'):
            filepath = os.path.join(self.path, 'result/sc_marker', filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'rb') as f:
                    file_content = f.read()
                    import base64
                    file_content_base64 = base64.b64encode(file_content).decode('utf-8')
                    res = {'filename': filename, 'file_content': file_content_base64, 'status': 'success', 'message': "read file successfully."}
            except Exception as e:
                print(f"Error reading file: {e}")
                res = {'status': 'fail', 'message': "File cannot be read."}
        else:
            print(f"{filename} does not exist in {filepath}")
            res = {'status': 'fail', 'message': "File is not existed."}
        return res
    
    def getdownloadfilelist(self, flag):
        filelist = {}
        if flag == "input":
            filelist['csv'] = []
            input_dir_path = os.path.join(self.path, 'result/sc_marker')
            if os.path.exists(input_dir_path):
                for file in os.listdir(input_dir_path):
                    if file.endswith('_marker.csv') or file.endswith('_clusters.csv'):
                        filelist['csv'].append(file)
            else:
                print(f"Directory {input_dir_path} does not exist.")
        elif flag == "output":
            filelist['h5ad'] = []
            output_h5ad_dir_path = os.path.join(self.path, 'result/sc_query/annotation_h5ad')
            if os.path.exists(output_h5ad_dir_path):
                for file in os.listdir(output_h5ad_dir_path):
                    if file.endswith('.h5ad'):
                        filelist['h5ad'].append(file)
            else:
                print(f"Directory {output_h5ad_dir_path} does not exist.")
            
            filelist['meta'] = []
            output_meta_dir_path = os.path.join(self.path, 'result/meta')
            if os.path.exists(output_meta_dir_path):
                for file in os.listdir(output_meta_dir_path):
                    if file.endswith('_meta_data_addquerycell.txt'):
                        filelist['meta'].append(file)
            else:
                print(f"Directory {output_meta_dir_path} does not exist.")
        else:
            res = {'status': 'fail', 'message': "Wrong filelist type."}
            return res
        res = {'filelist': filelist, 'flag': flag, 'status': 'success'}
        return res
