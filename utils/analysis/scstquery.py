import os
import glob
import json
import time
import subprocess
import pickle
import numpy as np
import pandas as pd
import scanpy as sc
from scipy import sparse
from pathlib import Path
from django.http import HttpResponse
from scdb_api import settings_local as local_settings
from utils.page import paginate_dataframe
from task.spider_service import get_spider_metadata, get_pattern_data, get_lr_data
from task.apps import r_proxy
from dataset.models import Dataset
from .base import Module


class Scstquery(Module):
    def __init__(self, name,path,params):
        super().__init__(name,path)
        print('params', params)
        inputfilepath=local_settings.USERTASKPATH +path+'/upload/input.h5ad'
        outputdir=local_settings.USERTASKPATH +path+'/result/'
        paramk=str(params['k'])
        projectname=params['projectname']
        organs=params['organParts']
        disease=params['disease']
        if params['processType'] == "cluster":
            self.script_arguments = [inputfilepath,outputdir,projectname,'190','1.2','cluster',organs]
        elif params['processType'] == "celltype":
            self.script_arguments = [inputfilepath,outputdir,projectname,'190','1.2','cell_type',organs,disease]
        #/home/platform/project/scdb_platform/scdb_api/workspace/module/scst_query/test3/test/sc_query
        self.shell_script = local_settings.SCDB_MODULE+'scst_query/run.sh'
        print(self.shell_script, self.script_arguments)
    
    def getOrgansAndDatasets(self):
        json_path = os.path.join(self.path, 'result/sc_query/result_scores.json')
        # json_path = "/home/platform/project/scdb_platform/scdb_api/workspace/module/scst_query/test3/test/sc_query/result_scores.json"
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

        # 3. Load subtask info for this task
        # subtask_map: dataset_path -> {cache_key: {id, status, job_id, subtask_type, mapping_method}}
        # For commot/cellchat/spider, cache_key includes mapping_method so that
        # multiple per-method subtasks are preserved (e.g. "commot__cytospace",
        # "commot__hierarchical_clustering") instead of being de-duplicated to
        # only the latest one.
        INTERACTION_TYPES = {'commot', 'cellchat', 'spider'}
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

        # 4. 数据转换与数据库关联
        transformed_data = {}

        for organ_name, datasets_dict in raw_data.items():
            transformed_data[organ_name] = {}
            
            for original_path, scores in datasets_dict.items():
                # === A. 提取 UUID (marker_path 里 st_marker 前一段 = Dataset.title) ===
                # 路径示例: .../thymus/7426a474.../st_marker/test_marker.csv
                # 用 _extract_dataset_uuid 取 st_marker 前一段,比 parts[-3] 更稳(兼容非扁平 marker 路径)
                extracted_uuid = self._extract_dataset_uuid(original_path) or ""

                # === B. 数据库查询 ===
                db_obj = None
                if extracted_uuid:
                    # 注意：根据您的描述，UUID 存在 'title' 字段中
                    # 我们要获取的是 'dataset_id' 字段 (如 Thymus_Normal_017)
                    db_obj = Dataset.objects.filter(title=extracted_uuid).first()

                # === C. 构建新的 Key 和 Value ===
                if db_obj:
                    # 查到了：使用 dataset_id 作为新的 Key
                    new_key = db_obj.dataset_id
                    
                    # 构造更丰富的描述
                    description = f"{db_obj.disease} | {db_obj.n_spots} spots | {db_obj.n_donors} donors"
                    
                    # 构造元数据
                    meta_info = {
                        "dataset_id": db_obj.dataset_id,
                        "uuid": extracted_uuid,
                        "disease": db_obj.disease,
                        "n_spots": db_obj.n_spots,
                        "organ": db_obj.organ,
                        "h5ad_path": db_obj.file_path # 数据库里存的原始h5ad路径
                    }
                else:
                    # 没查到：使用 UUID 或 文件名 作为 Key (Fallback)
                    new_key = extracted_uuid if extracted_uuid else os.path.basename(original_path)
                    description = "Unknown Dataset"
                    meta_info = {"uuid": extracted_uuid}

                # === D. 组装最终对象 ===
                # 将原始的分数信息复制过来
                new_value = scores.copy()
                
                # 添加关键字段
                new_value['marker_path'] = original_path  # ★ 原来的 Key 变成了 Value 里的 marker_path
                new_value['title'] = new_key              # 显式添加 title 字段，方便前端
                new_value['description'] = description    # 拼装好的描述
                new_value['meta'] = meta_info             # 详细元数据

                # Attach subtask info
                # subtask_map is keyed by SubTask.dataset_path: dataset_id for new rows,
                # marker_path for legacy rows. Try dataset_id first, then marker_path.
                _subtasks = subtask_map.get(db_obj.dataset_id if db_obj else None, {}) \
                    or subtask_map.get(original_path, {})
                new_value['subtasks'] = _subtasks

                # 放入新的字典中
                transformed_data[organ_name][new_key] = new_value

        return {
            'status': 'success',
            'data': transformed_data
        }
    
    def getDatasetInfo(self, datasetPath):
        from pathlib import Path

        # 读取 marker 表
        dataset_marker_df = pd.read_csv(datasetPath)
        num_rows_marker, num_columns_marker = dataset_marker_df.shape

        # 读取 clusters 表
        dataset_clusters_path = datasetPath.replace("_marker.csv", "_clusters.csv")
        dataset_clusters_df = pd.read_csv(dataset_clusters_path)
        num_rows_clusters, num_columns_clusters = dataset_clusters_df.shape

        # 构造 filtered adata 路径
        old_path = Path(datasetPath)
        filtered_adata_path = old_path.parent.parent / "st_filtered_adata" / (old_path.stem.replace("_marker", "_filtered") + ".h5ad")

        # 读取 filtered adata
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
        metadata=paginate_dataframe(metadata, page, pagesize) # paginate the metadata
        res={'results': metadata.to_dict(orient='records'), 'count': count}
        return res
    
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
        res = {'scatter': query_count_result.to_dict(orient='index'), 'cluster_celltype_distribution': cluster_celltype_distribution_data, 'status': 'success'}
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
        res = {'scatter': query_count_result.to_dict(orient='index'), 'status': 'success'}
        return res
        
    def getHierarchicalClusteringQueryCelltypes(self, dataset):
        subtask_he = self._resolve_subtask_he_path(dataset)
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        hierarchicalClustering_dir_path = os.path.join(base, 'HierarchicalClustering')
        celltypes = []
        if os.path.isdir(hierarchicalClustering_dir_path):
            for file_name in os.listdir(hierarchicalClustering_dir_path):
                if file_name.endswith("_merged_data_with_labels.csv"):
                    start = file_name.find("cluster") + len("cluster")
                    end = file_name.find("_merged_data_with_labels.csv")
                    if start != -1 and end != -1:
                        extracted_part = file_name[start:end]
                        celltype = extracted_part.replace("_", " ").strip()
                        celltypes.append(celltype)
        res = {'hierarchicalClusteringQueryCelltypes': celltypes,  'status': 'success'}
        return res
        
    def getHierarchicalClusteringQueryCountHeatmapResult(self, dataset, cluster):
        subtask_he = self._resolve_subtask_he_path(dataset)
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        HierarchicalClustering_result_dir_path = os.path.join(base, 'HierarchicalClustering/')
        file_name = "cluster" + cluster.replace(" ", "_") + "_merged_data_with_labels.csv"
        file_path = os.path.join(HierarchicalClustering_result_dir_path, file_name)
        if not os.path.exists(file_path):
            return {'status': 'fail', 'message': f'File not found: {file_path}'}
        cluster_HierarchicalClustering_query_count_result = pd.read_csv(file_path, index_col=0)
        cluster_HierarchicalClustering_query_count_result = cluster_HierarchicalClustering_query_count_result.replace({np.nan: None})
        if 'clusters' in cluster_HierarchicalClustering_query_count_result.columns:
            cluster_HierarchicalClustering_query_count_result = cluster_HierarchicalClustering_query_count_result.drop(columns=['clusters'])
        cluster_HierarchicalClustering_query_count_result['Label'] = cluster_HierarchicalClustering_query_count_result['Label'].astype(str)
        res = {'scatter': cluster_HierarchicalClustering_query_count_result.to_dict(orient='index'), 'status': 'success'}
        return res
    
    def getHierarchicalClusteringMarkerGenes(self, dataset, cluster):
        subtask_he = self._resolve_subtask_he_path(dataset)
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        expression_file_path = os.path.join(base, 'gene_expression.csv')
        if not os.path.exists(expression_file_path):
            return {'status': 'fail', 'message': f'File not found: {expression_file_path}'}
        expression_df = pd.read_csv(expression_file_path, index_col=0)
        HierarchicalClustering_result_dir_path = os.path.join(base, 'HierarchicalClustering/')
        file_name = "cluster" + cluster.replace(" ", "_") + "_merged_data_with_labels.csv"
        cluster_file_path = os.path.join(HierarchicalClustering_result_dir_path, file_name)
        if not os.path.exists(cluster_file_path):
            return {'status': 'fail', 'message': f'File not found: {cluster_file_path}'}
        cluster_HierarchicalClustering_query_count_result = pd.read_csv(cluster_file_path, index_col=0)
        
        st_names = cluster_HierarchicalClustering_query_count_result.index.tolist()
        
        # 过滤出存在于DataFrame索引中的st_names
        valid_st_names = [name for name in st_names if name in expression_df.index]
        
        if not valid_st_names:
            return {'expression': {}, 'status': 'success'}
        
        filtered_df = expression_df.loc[valid_st_names]
        filtered_df = filtered_df.loc[:, (filtered_df != 0).any(axis=0)]
        
        # 计算每个列的非零值次数，排序并选取前 50 列
        top_genes = (filtered_df != 0).sum(axis=0).nlargest(50).index.tolist()
        
        # 返回结果，只包含前 50 个基因列
        filtered_df = filtered_df[top_genes]
        
        res = {'genes': top_genes, 'status': 'success'}

        return res
    
    def getHierarchicalClusteringStatus(self):
        dir_path = os.path.join(self.path, "result/he/HierarchicalClustering")
        has_data = os.path.isdir(dir_path) and len(os.listdir(dir_path)) > 0
        return {"hierarchicalCluster_status": has_data, "status": "success"}

    def getHierarchicalClusteringMarkerGeneExpressions(self, dataset, cluster, gene):
        subtask_he = self._resolve_subtask_he_path(dataset)
        base = subtask_he if subtask_he else os.path.join(self.path, 'result/he')
        expression_file_path = os.path.join(base, 'gene_expression.csv')
        if not os.path.exists(expression_file_path):
            return {'status': 'fail', 'message': f'File not found: {expression_file_path}'}
        expression_df = pd.read_csv(expression_file_path, index_col=0)
        HierarchicalClustering_result_dir_path = os.path.join(base, 'HierarchicalClustering/')
        file_name = "cluster" + cluster.replace(" ", "_") + "_merged_data_with_labels.csv"
        cluster_file_path = os.path.join(HierarchicalClustering_result_dir_path, file_name)
        if not os.path.exists(cluster_file_path):
            return {'status': 'fail', 'message': f'File not found: {cluster_file_path}'}
        cluster_HierarchicalClustering_query_count_result = pd.read_csv(cluster_file_path, index_col=0)
        
        st_names = cluster_HierarchicalClustering_query_count_result.index.tolist()
        
        # 过滤出存在于DataFrame索引中的st_names
        valid_st_names = [name for name in st_names if name in expression_df.index]
        
        if not valid_st_names:
            return {'expression': {}, 'status': 'success'}
        
        filtered_df = expression_df.loc[valid_st_names]
        filtered_df = filtered_df.loc[:, (filtered_df != 0).any(axis=0)]
        
        if gene not in filtered_df.columns:
            return {'expression': {}, 'status': 'gene_not_found'}
        
        gene_expression = filtered_df[[gene]]
        
        res = {'expression': gene_expression.to_dict(orient='index'), 'status': 'success'}

        return res
    
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
            # New path: sc_st_mapping/{method}/
            if mapping_method:
                new_dir = os.path.join(base, 'sc_st_mapping', mapping_method)
                if os.path.isdir(new_dir):
                    print(f"[commot] using method dir: {new_dir}")
                    return new_dir
            # Fallback: old flat path
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
            'x': spatial_coords[:, 0],  # X 坐标
            'y': spatial_coords[:, 1],  # Y 坐标
            lr_pair: receiver_strength  # 接收信号强度
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
        
            
    def download(self, filename):
        if filename.endswith('.h5ad'):
            filepath = os.path.join(self.path, 'result/sc_query/annotation_h5ad', filename)
        elif filename.endswith('.txt'):
            filepath = os.path.join(self.path, 'result/meta', filename)
        elif filename.endswith('.csv'):
            filepath = os.path.join(self.path, 'result/sc_marker', filename)
        print(filepath)
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
        # input
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
    
    def getImgpath(self, analysis_type, image_ID):
        if analysis_type == "he":
            dataset_id = image_ID
            try:
                from dataset.models import Dataset
                import h5py
                ds = Dataset.objects.get(dataset_id=dataset_id)
                png_path = ds.file_path.replace(".h5ad", "_tissue_hires.png")
                if not os.path.exists(png_path):
                    with h5py.File(ds.file_path, "r") as f:
                        if "uns/spatial" not in f:
                            return ""
                        for lib in f["uns/spatial"].keys():
                            for img_key in ("hires", "lowres"):
                                img_full = f"uns/spatial/{lib}/images/{img_key}"
                                if img_full in f:
                                    from PIL import Image
                                    Image.fromarray(f[img_full][:]).save(png_path)
                                    return png_path
                    return ""
                return png_path
            except Exception as e:
                print(f"[tissue_image] error for {dataset_id}: {e}")
                return ""
        return ""
    def run_cellchat_api(self, rds_path, method, signaling=None, lrpair=None, output_file=None):
        import time, os, subprocess, json

        if output_file is None:
            timestamp = int(time.time())
            filename = f"api_{method}_{signaling or 'default'}_{timestamp}.json"
            output_file = os.path.join("/tmp", filename)

        cmd = [
            "/data3/platform/sc_db/miniconda3/bin/conda", "run", "-p", "/data3/platform/sc_db/cellchat/env",
            "Rscript", "/data3/platform/sc_db/cellchat/api/api.R",
            f"--rds_path={rds_path}",
            f"--method={method}",
            f"--output_file={output_file}"
        ]
        if signaling:
            cmd.append(f"--signaling={signaling}")
        if lrpair:
            cmd.append(f"--lrpair={lrpair}")

        print("Running command:", " ".join(cmd))

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if os.path.exists(output_file):
                os.unlink(output_file)
            raise RuntimeError(f"R script error: {result.stderr}")

        # 读取 JSON
        if os.path.exists(output_file):
            try:
                with open(output_file, 'r') as f:
                    output = json.load(f)
                os.unlink(output_file)  # 清理
                return output
            except json.JSONDecodeError as e:
                os.unlink(output_file)
                print("Raw R output:\n", result.stdout)
                raise e
        else:
            raise RuntimeError("Output file not created")

    
    def _find_cellchat_rds(self, dataset, mapping_method=None):
        """根据 dataset_id 定位 subtask_cellchat 的 RDS 文件"""
        if getattr(self, '_is_demo', False):
            if mapping_method:
                method_path = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, 'cellchat_result.rds')
                if os.path.exists(method_path):
                    return method_path
            rds_files = glob.glob(os.path.join(self.path, 'result', 'cellchat', '*.rds'))
            return rds_files[0] if rds_files else None
        if not dataset:
            raise ValueError('dataset is required')
        try:
            db_obj = Dataset.objects.get(dataset_id=dataset)
        except Dataset.DoesNotExist:
            return None
        base = os.path.join(self.path, f'dataset_{db_obj.title}', 'subtask_cellchat', 'result')
        # New path: sc_st_mapping/{method}/ or sc/
        if mapping_method:
            new_path = os.path.join(base, 'sc_st_mapping', mapping_method, 'cellchat_result.rds')
            if os.path.exists(new_path):
                return new_path
        # Fallback: old flat path
        old_path = os.path.join(base, 'cellchat_result.rds')
        return old_path if os.path.exists(old_path) else None

    def getCellChatPathways(self, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_pathways(rds_path)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatCircleData(self, pathway, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_circle(rds_path, signaling=pathway)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatSpatialData(self, pathway, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_spatial(rds_path, signaling=pathway)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatHeatmapData(self, LR_pair, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_heatmap(rds_path, lrpair=LR_pair)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatLRPairs(self, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_pairLRs(rds_path)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def _find_spider_h5ad(self, dataset_id, mapping_method=None):
        if dataset_id:
            try:
                ds = Dataset.objects.get(dataset_id=dataset_id)
                uuid = ds.title
                base = os.path.join(self.path, f'dataset_{uuid}', 'subtask_spider', 'result')
                # New path: sc_st_mapping/{method}/
                if mapping_method:
                    new_path = os.path.join(base, 'sc_st_mapping', mapping_method, 'adata_spider.h5ad')
                    if os.path.exists(new_path):
                        return new_path
                # Fallback: old flat path
                old_path = os.path.join(base, 'adata_spider.h5ad')
                if os.path.exists(old_path):
                    return old_path
            except Dataset.DoesNotExist:
                pass
        return os.path.join(self.path, 'result/spider/adata_spider.h5ad')

    def getSpiderInit(self, dataset=None, mapping_method=None):
        """
        SPIDER 接口1：初始化，返回 Metadata 和 Coordinates
        """
        h5ad_path = self._find_spider_h5ad(dataset, mapping_method)
        if not os.path.exists(h5ad_path):
            return {'data': {}, 'status': 'error', 'message': f'File not found: {h5ad_path}'}

        try:
            adata = sc.read_h5ad(h5ad_path, backed='r')
            
            # --- 1. 构建元数据 (Patterns & LRs) ---
            metadata = []
            if 'pattern_score' in adata.obsm.keys():
                n_patterns = adata.obsm['pattern_score'].shape[1]
                
                for i in range(n_patterns):
                    pattern_item = {
                        "id": i,
                        "name": f"Pattern {i}",
                        "svis": []
                    }
                    
                    # 筛选属于该 Pattern 的 LR
                    if 'label' in adata.var.columns:
                        # backed 模式下，adata.var 是 DataFrame，可以直接操作
                        pattern_vars = adata.var[adata.var['label'] == i]
                        
                        # 尝试排序
                        corr_col = f'pattern_correlation_{i}'
                        if corr_col in pattern_vars.columns:
                            pattern_vars = pattern_vars.sort_values(by=corr_col, ascending=False)
                        
                        # 取 Top 10
                        top_vars = pattern_vars.head(10)
                        
                        for lr_name, row in top_vars.iterrows():
                            score = row.get(corr_col, 0)
                            pattern_item['svis'].append({
                                "name": lr_name,
                                "score": round(float(score), 3)
                            })
                    
                    metadata.append(pattern_item)
            
            # --- 2. 构建坐标 (Coordinates) ---
            coordinates = []
            if 'row' in adata.obs.columns and 'col' in adata.obs.columns:
                rows = adata.obs['row'].values
                cols = adata.obs['col'].values
                obs_names = adata.obs_names
                
                # 为了性能，使用列表推导式
                coordinates = [
                    {"id": name, "x": float(r), "y": float(c)} 
                    for name, r, c in zip(obs_names, rows, cols)
                ]

            return {
                'data': {
                    'metadata': metadata,
                    'coordinates': coordinates
                },
                'status': 'success'
            }
            
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getSpiderPatternData(self, dataset=None, pattern_id=None, mapping_method=None):
        """
        SPIDER 接口2：获取指定 Pattern 的评分
        """
        h5ad_path = self._find_spider_h5ad(dataset, mapping_method)
        try:
            if pattern_id is None:
                raise ValueError("Pattern ID is required")
                
            pid = int(pattern_id)
            adata = sc.read_h5ad(h5ad_path, backed='r')
            
            if 'pattern_score' not in adata.obsm.keys():
                 raise ValueError("pattern_score not found in data")

            # 读取那一列数据
            scores = adata.obsm['pattern_score'][:, pid]
            
            return {
                'data': scores.flatten().tolist(),
                'status': 'success'
            }
        except Exception as e:
            return {'data': [], 'status': 'error', 'message': str(e)}

    def getSpiderLRData(self, dataset=None, lr_name=None, mapping_method=None):
        """
        SPIDER 接口3：获取指定 LR 的表达量
        """
        h5ad_path = self._find_spider_h5ad(dataset, mapping_method)
        try:
            if not lr_name:
                raise ValueError("LR Name is required")
                
            adata = sc.read_h5ad(h5ad_path, backed='r')
            
            if lr_name not in adata.var_names:
                return {'data': [], 'status': 'error', 'message': f'LR pair {lr_name} not found'}

            # 获取表达矩阵中的那一列
            # 注意：adata[:, name] 会返回一个切片视图
            data_col = adata[:, lr_name].X
            
            # 兼容稀疏矩阵和普通矩阵
            if sparse.issparse(data_col):
                values = data_col.toarray().flatten()
            else:
                values = data_col.flatten()

            return {
                'data': values.tolist(),
                'status': 'success'
            }
        except Exception as e:
            return {'data': [], 'status': 'error', 'message': str(e)}

    def getSpiderSpearmanData(self, dataset=None, mapping_method=None):
        base_dir = os.path.join(self.path, f'dataset_{dataset}', 'subtask_spider', 'result') if dataset else os.path.join(self.path, 'result/spider')
        # If mapping_method specified, try method-specific subdirectory first
        if mapping_method:
            method_dir = os.path.join(base_dir, 'sc_st_mapping', mapping_method)
            method_sc_path = os.path.join(method_dir, 'spearman/lr_level_spearman_correlation_sc.csv')
            method_sc_st_path = os.path.join(method_dir, 'spearman/lr_level_spearman_correlation_sc_st.csv')
            if os.path.exists(method_sc_st_path):
                sc_path = method_sc_path
                sc_st_path = method_sc_st_path
            else:
                sc_path = os.path.join(base_dir, 'spearman/lr_level_spearman_correlation_sc.csv')
                sc_st_path = os.path.join(base_dir, 'spearman/lr_level_spearman_correlation_sc_st.csv')
        else:
            sc_path = os.path.join(base_dir, 'spearman/lr_level_spearman_correlation_sc.csv')
            sc_st_path = os.path.join(base_dir, 'spearman/lr_level_spearman_correlation_sc_st.csv')
        
        results = []
        
        def clean_val(val, default_val):
            try:
                if pd.isna(val): return default_val
                if isinstance(val, (int, float)) and np.isinf(val): return default_val
                return float(val)
            except:
                return default_val
        
        # 辅助函数：处理整数 (n_receivers)
        def clean_int(val, default_val=0):
            try:
                if pd.isna(val): return default_val
                return int(val)
            except:
                return default_val

        try:
            # --- SC ---
            if os.path.exists(sc_path):
                df_sc = pd.read_csv(sc_path)
                for _, row in df_sc.iterrows():
                    results.append({
                        "id": str(row.get('lr_pair', 'unknown')),
                        "type": "SC",
                        "spearman_rho": clean_val(row.get('spearman_rho'), 0),
                        "spearman_pval": clean_val(row.get('spearman_pval'), 1.0),
                        # 新增字段
                        "n_receivers": clean_int(row.get('n_receivers'), 0),
                        "mean_activity": clean_val(row.get('mean_activity'), 0),
                        "mean_max_ccc": clean_val(row.get('mean_max_ccc'), 0)
                    })

            # --- SC + ST ---
            if os.path.exists(sc_st_path):
                df_scst = pd.read_csv(sc_st_path)
                for _, row in df_scst.iterrows():
                    results.append({
                        "id": str(row.get('lr_pair', 'unknown')),
                        "type": "SC + ST",
                        "spearman_rho": clean_val(row.get('spearman_rho'), 0),
                        "spearman_pval": clean_val(row.get('spearman_pval'), 1.0),
                        # 新增字段
                        "n_receivers": clean_int(row.get('n_receivers'), 0),
                        "mean_activity": clean_val(row.get('mean_activity'), 0),
                        "mean_max_ccc": clean_val(row.get('mean_max_ccc'), 0)
                    })

            return {'data': results, 'status': 'success'}

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'data': [], 'status': 'error', 'message': str(e)}
        
    def getAlphaTalkLRPairs(self, page=1, pageSize=15, 
                            sender=None, receiver=None, ligand=None, receptor=None, type_col=None,
                            min_score=None, max_score=None,
                            min_lr_score=None, max_lr_score=None,
                            min_p_value=None, max_p_value=None,
                            sortBy=None, order=None, get_metadata=None):
        
        pkl_path = os.path.join(self.path, 'result/alphatalk/cci_result.pkl')

        try:
            # 1. 加载文件
            if not os.path.exists(pkl_path):
                return {'data': [], 'total': 0, 'status': 'error', 'message': "File not found"}

            with open(pkl_path, 'rb') as f:
                result_obj = pickle.load(f)

            if 'lr_score' not in result_obj:
                return {'data': [], 'total': 0, 'status': 'error', 'message': "Invalid data format"}
            
            df = result_obj['lr_score']

            if df.empty:
                return {'data': [], 'total': 0, 'status': 'success', 'message': "Empty result"}

            # =========================================================
            # 🔥 重点：先执行所有筛选逻辑 (Filtering)
            # =========================================================
            
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

            # =========================================================
            # 🔥 重点：筛选完后，再返回元数据
            # 此时的 df 已经是过滤后的子集了，所以 unique() 只会包含剩下的选项
            # =========================================================
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

            # =========================================================
            # 后续：排序、分页、格式化 (保持不变)
            # =========================================================
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
    
    def getresult(self,query_params):
        resulttype = query_params.get('resulttype')
        if resulttype == 'metadata':
            return self.getmetaresult(int(query_params.get('page')), int(query_params.get('pagesize')))
        elif resulttype == 'organsanddatasets':
            return self.getOrgansAndDatasets()
        elif resulttype == 'datasetInfo':
            return self.getDatasetInfo(query_params.get('datasetPath'))
        elif resulttype == 'filelist':
            return self.getdownloadfilelist(query_params.get('flag'))
        elif resulttype == 'scstmappingDownload':
            return self._scstmapping_resolve_file(query_params.get('dataset'), query_params.get('method'))
        elif resulttype == 'download':
            return self.download(query_params.get('filename'))
        elif resulttype == 'hescatter':
            return self.getHEScatterresult(query_params.get('dataset'))
        elif resulttype == 'countHeatmap':
            return self.getQueryCountHeatmapResult(query_params.get('dataset'))
        elif resulttype == 'hierarchicalClusteringStatus':
            return self.getHierarchicalClusteringStatus()
        elif resulttype == 'hierarchicalclusteringCelltypes':
            return self.getHierarchicalClusteringQueryCelltypes(query_params.get('dataset'))
        elif resulttype == 'hierarchicalclusteringCountHeatmap':
            return self.getHierarchicalClusteringQueryCountHeatmapResult(query_params.get('dataset'), query_params.get('cluster'))
        elif resulttype == 'hierarchicalClusteringMarkerGenes':
            return self.getHierarchicalClusteringMarkerGenes(query_params.get('dataset'), query_params.get('cluster'))
        elif resulttype == 'hierarchicalClusteringMarkerGeneExpressions':
            return self.getHierarchicalClusteringMarkerGeneExpressions(query_params.get('dataset'), query_params.get('cluster'), query_params.get('gene'))
        elif resulttype == 'LRPairs':
            return self.getLRPairs(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'LRreceivedSignalStrength':
            return self.getReceivedSignalStrength(query_params.get('dataset'), query_params.get('lr_pair'), query_params.get('mapping_method'))
        elif resulttype == 'networkData':
            return self.getNetworkData(query_params.get('dataset'), query_params.get('type'), query_params.get('mapping_method'))
        elif resulttype == 'img_path':
            return self.getImgpath(query_params.get('analysis_type'), query_params.get('img_id'))
        elif resulttype == 'cellchat_pathways':
            return self.getCellChatPathways(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'cellchat_circle':
            return self.getCellChatCircleData(query_params.get('pathway'), query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'cellchat_spatial':
            return self.getCellChatSpatialData(query_params.get('pathway'), query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'cellchat_heatmap':
            return self.getCellChatHeatmapData(query_params.get('LR_pair'), query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'cellchat_lrpairs':
            return self.getCellChatLRPairs(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'spider_init':
            return self.getSpiderInit(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'spider_pattern':
            return self.getSpiderPatternData(query_params.get('dataset'), query_params.get('pattern_id'), query_params.get('mapping_method'))
        elif resulttype == 'spider_lr':
            return self.getSpiderLRData(query_params.get('dataset'), query_params.get('lr_name'), query_params.get('mapping_method'))
        elif resulttype == 'spider_spearman':
            return self.getSpiderSpearmanData(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'scstmappingStatus':
            return self._scstmappingStatusFallback(query_params.get('dataset'))
        else:
            expressionfile=self.path+ '/result/scquery/sc_output_expression.csv'
            expression = pd.read_csv(expressionfile, index_col=0)
            return {'results': expression.to_dict(orient='records')}

    def gettestresult(self,query_params):
        self.path = local_settings.USERTASKPATH + 'demo_result/scst'
        self._is_demo = True
        print(self.path)
        resulttype = query_params.get('resulttype')
        if resulttype == 'metadata':
            return self.getmetaresult(int(query_params.get('page')), int(query_params.get('pagesize')))
        elif resulttype == 'organsanddatasets':
            return self.getOrgansAndDatasets()
        elif resulttype == 'filelist':
            return self.getdownloadfilelist(query_params.get('flag'))
        elif resulttype == 'scstmappingDownload':
            return self._scstmapping_resolve_file(query_params.get('dataset'), query_params.get('method'))
        elif resulttype == 'download':
            return self.download(query_params.get('filename'))
        elif resulttype == 'hescatter':
            return self.getHEScatterresult(query_params.get('dataset'))
        elif resulttype == 'countHeatmap':
            return self.getQueryCountHeatmapResult(query_params.get('dataset'))
        elif resulttype == 'hierarchicalClusteringStatus':
            return self.getHierarchicalClusteringStatus()
        elif resulttype == 'hierarchicalclusteringCelltypes':
            return self.getHierarchicalClusteringQueryCelltypes(query_params.get('dataset'))
        elif resulttype == 'hierarchicalclusteringCountHeatmap':
            return self.getHierarchicalClusteringQueryCountHeatmapResult(query_params.get('dataset'), query_params.get('cluster'))
        elif resulttype == 'hierarchicalClusteringMarkerGenes':
            return self.getHierarchicalClusteringMarkerGenes(query_params.get('dataset'), query_params.get('cluster'))
        elif resulttype == 'hierarchicalClusteringMarkerGeneExpressions':
            return self.getHierarchicalClusteringMarkerGeneExpressions(query_params.get('dataset'), query_params.get('cluster'), query_params.get('gene'))
        elif resulttype == 'LRPairs':
            return self.getLRPairs(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'LRreceivedSignalStrength':
            return self.getReceivedSignalStrength(query_params.get('dataset'), query_params.get('lr_pair'), query_params.get('mapping_method'))
        elif resulttype == 'cellchat_pathways':
            return self.getCellChatPathways(mapping_method=query_params.get('mapping_method'))
        elif resulttype == 'cellchat_circle':
            return self.getCellChatCircleData(query_params.get('pathway'), mapping_method=query_params.get('mapping_method'))
        elif resulttype == 'cellchat_spatial':
            return self.getCellChatSpatialData(query_params.get('pathway'), mapping_method=query_params.get('mapping_method'))
        elif resulttype == 'cellchat_heatmap':
            return self.getCellChatHeatmapData(query_params.get('LR_pair'), mapping_method=query_params.get('mapping_method'))
        elif resulttype == 'cellchat_lrpairs':
            return self.getCellChatLRPairs(mapping_method=query_params.get('mapping_method'))
        elif resulttype == 'spider_init':
            # 获取元数据和坐标
            return self.getSpiderInit(query_params.get('dataset'), query_params.get('mapping_method'))
            
        elif resulttype == 'spider_pattern':
            # 获取特定 Pattern 的数值
            return self.getSpiderPatternData(query_params.get('dataset'), query_params.get('pattern_id'), query_params.get('mapping_method'))
            
        elif resulttype == 'spider_lr':
            # 获取特定 LR 的数值
            return self.getSpiderLRData(query_params.get('dataset'), query_params.get('lr_name'), query_params.get('mapping_method'))
        elif resulttype == 'spider_spearman':
            # --- 新增：Spearman 分析数据接口 ---
            return self.getSpiderSpearmanData(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'scstmappingStatus':
            return self._scstmappingStatusFallback(query_params.get('dataset'))
        elif resulttype == 'AlphaTalk':
            return self.getAlphaTalkLRPairs(
                page=query_params.get('page', 1),
                pageSize=query_params.get('pageSize', 15),
                sender=query_params.get('sender'),
                receiver=query_params.get('receiver'),
                ligand=query_params.get('ligand'),
                sortBy=query_params.get('sortBy'),
                order=query_params.get('order'),
                min_score=query_params.get('min_score'),
                max_score=query_params.get('max_score'),
                get_metadata=query_params.get('get_metadata'),
                receptor=query_params.get('receptor'),
                type_col=query_params.get('type'), # 注意参数名防止冲突
                min_lr_score=query_params.get('min_lr_score'),
                max_lr_score=query_params.get('max_lr_score'),
                min_p_value=query_params.get('min_p_value'),
                max_p_value=query_params.get('max_p_value'),
            )
        elif resulttype == 'networkData':
            return self.getNetworkData(query_params.get('dataset'), query_params.get('type'))
        elif resulttype == 'img_path':
            return self.getImgpath(query_params.get('analysis_type'), query_params.get('img_id'))
        else:
            expressionfile=self.path+ '/result/scquery/sc_output_expression.csv'
            expression = pd.read_csv(expressionfile, index_col=0)
            return {'results': expression.to_dict(orient='records')}
