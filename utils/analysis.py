from utils import slurm_api
from scdb_api import settings_local as local_settings
import pandas as pd
from utils.page import paginate_dataframe
from utils.fileprocess import get_gene_list,get_cluster_list
import os
import glob
import json
from django.http import HttpResponse
import numpy as np
import scanpy as sc
from scipy import sparse
#define a module class in analysis.py
import subprocess
import time
from task.spider_service import get_spider_metadata, get_pattern_data, get_lr_data
import sys
import pickle
from task.apps import r_proxy
from dataset.models import Dataset
# if (
#     any(cmd in sys.argv for cmd in ["runserver", "gunicorn", "uwsgi"])
#     and os.environ.get("RUN_MAIN") == "true"
# ):
#     # ✓ 真正 Web 子进程
#     print("🔹 Importing R service (web server mode)")
#     from task.cellchat_r_service import cellchat_service, RServiceError
# else:
#     # ✓ migrate/shell/test 模式
#     print("🔸 Skipping R service import (non-web mode)")
#     cellchat_service = None
#     RServiceError = None



class Module:
    def __init__(self, name,userpath):
        self.name = name
        self.job_id = None
        self.dependencies = []
        self.path = local_settings.USERTASKPATH+userpath
        self.status = 'Created'
        self.shell_script = None
        self.script_arguments = None

    def add_dependency(self, module):
        if not isinstance(module, Module):
            raise TypeError("Dependency must be an instance of Module or its subclasses.")
        self.dependencies.append(module)

    def check_status(self):
        # statuslist = ['PENDING', 'RUNNING', 'SUSPENDED', 'COMPLETING', 'COMPLETED','CANCELLED', 'FAILED', 'TIMEOUT', 'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL']
        if self.job_id is None:
            raise ValueError("Job ID is not set. Cannot check status.")
        self.status = slurm_api.get_job_status(self.job_id)
        return self.status

    def process(self):

        if self.shell_script is None:
            raise ValueError("Shell script is not set. Cannot process module.")
        if len(self.dependencies) == 0:
            #print(self.shell_script,self.script_arguments)
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments)
        else:
            dependencies_jobs = [dependency.job_id for dependency in self.dependencies if dependency.job_id is not None]
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments,dependency_job_ids=dependencies_jobs)
        self.status = 'Running'
        return self.job_id

# class Scquery_old(Module):
#     def __init__(self, name,path,params):
#         super().__init__(name,path)
#         inputfilepath=local_settings.USERTASKPATH +path+'/upload/query.csv'
#         outputdir=local_settings.USERTASKPATH +path+'/result/scquery'
#         paramk=str(params['k'])
#         self.script_arguments = [inputfilepath,paramk,outputdir]
#         #/home/platform/project/scdb_platform/scdb_api/workspace/module/sc_query_old
#         self.shell_script = local_settings.SCDB_MODULE+'sc_query_old/run.sh'

class Scquery(Module):
    def __init__(self, name,path,params):
        super().__init__(name,path)
        inputfilepath=local_settings.USERTASKPATH +path+'/upload/input.h5ad'
        outputdir=local_settings.USERTASKPATH +path+'/result/'
        paramk=str(params['k'])
        projectname=params['projectname']
        self.script_arguments = [inputfilepath,outputdir,projectname,'50','0.8']
        #/home/platform/project/scdb_platform/scdb_api/workspace/module/sc_query_old
        self.shell_script = local_settings.SCDB_MODULE+'sc_query/run.sh'
        
    def getmetaresult(self,page,pagesize):
        # metadatadir = os.path.join(self.path, '/result/meta/')
        # for filename in os.listdir(metadatadir):
        #     if filename.endswith('_meta_data_addquerycell.txt'):
        #         metadatafile = os.path.join(metadatadir, filename)
        #         metadata = pd.read_csv(metadatafile,sep='\t', index_col=False)
        #         count = metadata.shape[0]
        
        # metadatafile = self.path + f'/result/meta/{self.projectname}_{cluster_name}_meta_data_addquerycell.txt'
        metadatafile = self.path + f'/result/meta/test1_meta_data.txt'
        # metadatafile = "/data3/platform/sc_db/test/1024_1000scA/meta/test_cluster_1_meta_data_addquerycell.txt"
        metadata = pd.read_csv(metadatafile,sep='\t', index_col=False)
        count = metadata.shape[0]
        # rename_dict = {'index': 'Cell_id',
        #             'orig.ident':'orig_ident',
        #             'Celltype..malignancy.': 'Celltype_malignancy',
        #             'Celltype..major.lineage.':'Celltype_major_lineage'}
        # metadata.rename(columns=rename_dict, inplace=True) # rename the first column
        metadata.rename(columns={metadata.columns[0]: 'Cell_id'}, inplace=True)
        metadata=paginate_dataframe(metadata, page, pagesize) # paginate the metadata
        res={'results': metadata.to_dict(orient='records'), 'count': count}
        return res
    
    def getumapresult(self):
        umapfile=self.path+ f'/result/umap/test1_umap_data.txt'
        print('umap', umapfile)
        #umapfile=self.path+ f'/result/umap/{self.projectname}_umap_data.txt'
        umappddata = pd.read_csv(umapfile, sep='\t', index_col=False)
        rename_dict = {'cell_id': 'Cell_id',}
        umappddata.rename(columns=rename_dict, inplace=True)
        default_value = 'default'  # 可以是数字、字符串等
        umappddata_filled = umappddata.fillna(default_value)
        res={'results': umappddata_filled.to_dict(orient='records')}
        return res
    def getbatcheffect(self,compid,gene):
        genelist,gene_path_dict=get_gene_list(self.path+ '/result/batch_effect/batch_effected_split')
        geneoption=[{'value':gene,'label':gene} for gene in genelist]
        gene = gene if gene is not None else genelist[int(compid)]
        path=self.path+ '/result/batch_effect/batch_effected_split/'+gene_path_dict[gene]
        batcheffect_data=pd.read_csv(path,sep='\t',index_col=False,skiprows=1,header=None)
        batcheffect_data.rename(columns={0: 'Cell_id',1:'Gene'}, inplace=True) 
        res={'path':path,'results': batcheffect_data.to_dict(orient='records'),'geneoption': geneoption,'gene':gene}
        return res
    def getcasuality(self,cluster):
        cluster_input_list,inputdict=get_cluster_list(self.path+ '/result/casuality/input')
        cluster_output_list,outputdict=get_cluster_list(self.path+ '/result/casuality/output')
        clusteroption=[{'value':cluster,'label':"cluster_"+cluster} for cluster in cluster_input_list]
        cluster = cluster if cluster is not None else cluster_output_list[0]
        inputpath=self.path+ '/result/casuality/input/'+inputdict[cluster]
        outputpath=self.path+ '/result/casuality/output/'+outputdict[cluster]
        inputcasuality_data=pd.read_csv(inputpath,sep=',',index_col=False)
        outputcasuality_data=pd.read_csv(outputpath,sep=',',index_col=False)
        rename_dict = {'Unnamed: 0': 'gene'}
        inputcasuality_data.rename(columns=rename_dict, inplace=True) 
        outputcasuality_data.rename(columns=rename_dict, inplace=True)
        res={'results': {'inputdata':inputcasuality_data.to_dict(orient='records'),
                            'outputdata':outputcasuality_data.to_dict(orient='records')},
                            'clusteroption': clusteroption,'cluster':cluster}
        return res
    
    def download(self, filename):
        #TODO
        if filename.endswith('.h5ad'):
            # filepath = os.path.join(self.path, 'result/sc_query_output/h5ad', filename)
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
            # output_h5ad_dir_path = os.path.join(self.path, 'result/sc_query_output/h5ad')
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
    
    def getresult(self,query_params):
        resulttype = query_params.get('resulttype')
        if resulttype == 'metadata':
            return self.getmetaresult(int(query_params.get('page')), int(query_params.get('pagesize')))
        elif resulttype == 'umap':
            return self.getumapresult()
        elif resulttype == 'batcheffect':
            return self.getbatcheffect(query_params.get('compid'),query_params.get('gene'))
        elif resulttype == 'casuality':
            return self.getcasuality(query_params.get('cluster'))
        elif resulttype == 'filelist':
            return self.getdownloadfilelist(query_params.get('flag'))
        elif resulttype == 'download':
            return self.download(query_params.get('filename'))
        else:
            expressionfile=self.path+ '/result/scquery/sc_output_expression.csv'
            expression = pd.read_csv(expressionfile, index_col=0)
            return {'results': expression.to_dict(orient='records')}
# class Pipeline:
#     def __init__(self):
#         self.modules = []

#     def add_module(self, module):
#         self.modules.append(module)

#     def execute(self):
#         completed = set()

#         def execute_module(module):
#             for dependency in module.dependencies:
#                 if dependency not in completed:
#                     execute_module(dependency)
#             module.process()
#             completed.add(module)

#         for module in self.modules:
#             if module not in completed:
#                 execute_module(module)

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
            hierarchicalCluster = params['hierarchicalCluster']
            self.script_arguments = [inputfilepath,outputdir,projectname,'190','1.2','cell_type',str(hierarchicalCluster),organs,disease]
        #/home/platform/project/scdb_platform/scdb_api/workspace/module/sc_query_old
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

        # 3. 数据转换与数据库关联
        transformed_data = {}

        for organ_name, datasets_dict in raw_data.items():
            transformed_data[organ_name] = {}
            
            for original_path, scores in datasets_dict.items():
                # === A. 提取 UUID (对应 extractDatasetTitleFromPath 逻辑) ===
                # 路径示例: .../thymus/7426a474.../st_marker/test_marker.csv
                # split('/') 后倒数第三个就是 UUID
                parts = original_path.split('/')
                extracted_uuid = parts[-3] if len(parts) >= 3 else ""

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
        # metadatadir = os.path.join(self.path, '/result/meta/')
        # for filename in os.listdir(metadatadir):
        #     if filename.endswith('_meta_data_addquerycell.txt'):
        #         metadatafile = os.path.join(metadatadir, filename)
        #         metadata = pd.read_csv(metadatafile,sep='\t', index_col=False)
        #         count = metadata.shape[0]
        
        # metadatafile = self.path + f'/result/meta/{self.projectname}_{cluster_name}_meta_data_addquerycell.txt'
        metadatafile = self.path + f'/result/meta/test_cluster_1_meta_data_addquerycell.txt'
        # metadatafile = "/data3/platform/sc_db/test/1024_1000scA/meta/test_cluster_1_meta_data_addquerycell.txt"
        metadata = pd.read_csv(metadatafile,sep='\t', index_col=False)
        count = metadata.shape[0]
        # rename_dict = {'index': 'Cell_id',
        #             'orig.ident':'orig_ident',
        #             'Celltype..malignancy.': 'Celltype_malignancy',
        #             'Celltype..major.lineage.':'Celltype_major_lineage'}
        # metadata.rename(columns=rename_dict, inplace=True) # rename the first column
        metadata.rename(columns={metadata.columns[0]: 'Cell_id'}, inplace=True)
        metadata=paginate_dataframe(metadata, page, pagesize) # paginate the metadata
        res={'results': metadata.to_dict(orient='records'), 'count': count}
        return res
    
    # def getHEScatterresult(self, dataset):
    #     result_dict_path = os.path.join(self.path, 'result/he/path_map.json')
    #     cluster_celltype_distribution_filepath = os.path.join(self.path, "result/he/cluster_celltype_distribution.csv")
    #     with open(result_dict_path, 'r') as json_file:
    #         result_dict = json.load(json_file)
    #     keys_array = list(result_dict.keys())
    #     if dataset:
    #         if dataset in result_dict:
    #             scatter_csv_path = os.path.join(self.path, result_dict[dataset]["scatter_data_path"])
    #             # scatter_data.rename(columns={scatter_data.columns[0]: 'Cell_id'}, inplace=True)
    #         else:
    #             res = {'status': 'fail', 'message': f"dataset {dataset} is not in result!"}
    #             return res
    #     else:
    #         if keys_array:
    #             first_key = keys_array[0]
    #             scatter_csv_path = os.path.join(self.path, result_dict[first_key]["scatter_data_path"])
    #         else:
    #             res = {'status': 'fail', 'message': "no datasets in result!"}
    #             return res
    #     scatter_data = pd.read_csv(scatter_csv_path, sep='\t', index_col=False)
    #     cluster_celltype_distribution_data = pd.read_csv(cluster_celltype_distribution_filepath)
    #     res={'scatter': scatter_data.to_dict(orient='records'), 'datasets': keys_array, 'cluster_celltype_distribution': cluster_celltype_distribution_data.to_dict(orient='records'), 'status': 'success'}
    #     return res
    
    # def getQueryCountHeatmapResult(self, dataset):
    #     # 返回所有sc query st对应的搜索结果，里面有st出现的次数
    #     result_dict_path = os.path.join(self.path, 'result/he/path_map.json')
    #     cluster_celltype_distribution_filepath = os.path.join(self.path, "result/he/cluster_celltype_distribution.csv")
    #     with open(result_dict_path, 'r') as json_file:
    #         result_dict = json.load(json_file)
    #     keys_array = list(result_dict.keys())
    #     if dataset:
    #         if dataset in result_dict:
    #             scatter_csv_path = os.path.join(self.path, result_dict[dataset]["scatter_data_path"])
    #             # scatter_data.rename(columns={scatter_data.columns[0]: 'Cell_id'}, inplace=True)
    #         else:
    #             res = {'status': 'fail', 'message': f"dataset {dataset} is not in result!"}
    #             return res
    #     else:
    #         if keys_array:
    #             first_key = keys_array[0]
    #             scatter_csv_path = os.path.join(self.path, result_dict[first_key]["scatter_data_path"])
    #         else:
    #             res = {'status': 'fail', 'message': "no datasets in result!"}
    #             return res
    #     scatter_data = pd.read_csv(scatter_csv_path, sep='\t', index_col=False)
    #     cluster_celltype_distribution_data = pd.read_csv(cluster_celltype_distribution_filepath)
    #     res={'scatter': scatter_data.to_dict(orient='records'), 'datasets': keys_array, 'cluster_celltype_distribution': cluster_celltype_distribution_data.to_dict(orient='records'), 'status': 'success'}
    #     return res
    
    def getHEScatterresult(self, result):
        result_path = os.path.join(self.path, "result/he/all_merged_data_with_labels.csv")
        cluster_celltype_distribution_filepath = os.path.join(self.path, "result/he/cluster_celltype_distribution.json")
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE scatter data not found: {result_path}'}
        query_count_result = pd.read_csv(result_path, index_col=0)
        if 'clusters' in query_count_result.columns:
            query_count_result = query_count_result.drop(columns=['clusters'])
        query_count_result = query_count_result.replace({np.nan: None})
        cluster_celltype_distribution_data = {}
        if os.path.exists(cluster_celltype_distribution_filepath):
            with open(cluster_celltype_distribution_filepath, 'r') as json_file:
                cluster_celltype_distribution_data = json.load(json_file)
        res = {'scatter': query_count_result.to_dict(orient='index'), 'cluster_celltype_distribution': cluster_celltype_distribution_data, 'status': 'success'}
        return res
    
    def getQueryCountHeatmapResult(self, dataset):
        result_path = os.path.join(self.path, 'result/he/all_merged_data_with_labels.csv')
        if not os.path.exists(result_path):
            return {'status': 'fail', 'message': f'HE query count data not found: {result_path}'}
        query_count_result = pd.read_csv(result_path, index_col=0)
        if 'clusters' in query_count_result.columns:
            query_count_result = query_count_result.drop(columns=['clusters'])
        query_count_result = query_count_result.replace({np.nan: None})
        res = {'scatter': query_count_result.to_dict(orient='index'), 'status': 'success'}
        return res
        
    def getHierarchicalClusteringQueryCelltypes(self, dataset):
        hierarchicalClustering_dir_path = os.path.join(self.path, 'result/he/HierarchicalClustering')
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
        # 返回的是一个dict，里面是每个cluster/类型对应的sc query st的搜索结果的路径（放到另一个接口）
        # 返回层次聚类的某个clustercluster/类型的sc query st对应的搜索结果，里面有st出现的次数
        # TODO 这里要考虑不同dataset的情况
        HierarchicalClustering_result_dir_path = os.path.join(self.path, 'result/he/HierarchicalClustering/')
        file_name = "cluster" + cluster.replace(" ", "_") + "_merged_data_with_labels.csv"
        file_path = os.path.join(HierarchicalClustering_result_dir_path, file_name)
        if not os.path.exists(file_path):
            return {'status': 'fail', 'message': f'File not found: {file_path}'}
        cluster_HierarchicalClustering_query_count_result = pd.read_csv(file_path, index_col=0)
        cluster_HierarchicalClustering_query_count_result = cluster_HierarchicalClustering_query_count_result.replace({np.nan: None})
        if 'clusters' in cluster_HierarchicalClustering_query_count_result.columns:
            cluster_HierarchicalClustering_query_count_result = cluster_HierarchicalClustering_query_count_result.drop(columns=['clusters'])
        res = {'scatter': cluster_HierarchicalClustering_query_count_result.to_dict(orient='index'), 'status': 'success'}
        return res
    
    def getHierarchicalClusteringMarkerGenes(self, dataset, cluster):
        expression_file_path = os.path.join(self.path, 'result/he/markergeneexpression/output_600_marker_gene_expression.csv')
        if not os.path.exists(expression_file_path):
            return {'status': 'fail', 'message': f'File not found: {expression_file_path}'}
        expression_df = pd.read_csv(expression_file_path, index_col=0)
        
        HierarchicalClustering_result_dir_path = os.path.join(self.path, 'result/he/HierarchicalClustering/')
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
        expression_file_path = os.path.join(self.path, 'result/he/markergeneexpression/output_600_marker_gene_expression.csv')
        if not os.path.exists(expression_file_path):
            return {'status': 'fail', 'message': f'File not found: {expression_file_path}'}
        expression_df = pd.read_csv(expression_file_path, index_col=0)
        
        HierarchicalClustering_result_dir_path = os.path.join(self.path, 'result/he/HierarchicalClustering/')
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
    
    def getLRPairs(self, dataset):
        file_path = os.path.join(self.path, 'result/commot/test_result.h5ad')
        if not os.path.exists(file_path):
            return {'LR_pairs': [], 'status': 'error', 'message': f'File not found: {file_path}'}
        adata = sc.read(file_path)
        lr_pairs = adata.obsm['commot-cellchat-sum-receiver'].columns
        print('lr_pairs', lr_pairs)

        res = {'LR_pairs': lr_pairs.tolist(), 'status': 'success'}
        return res

    def getReceivedSignalStrength(self, dataset, lr_pair):
        file_path = os.path.join(self.path, 'result/commot/test_result.h5ad')
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
    
    def getNetworkData(self, dataset, type):
        if type == 'weight':
            file_path = os.path.join(self.path, 'result/cellchat/network/result_data_weight.json')
        elif type == 'count':
            file_path = os.path.join(self.path, 'result/cellchat/network/result_data_count.json')

        if not os.path.exists(file_path):
            return {'network_data': {}, 'status': 'error', 'message': f'File not found: {file_path}'}

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        res = {'network_data': data, 'status': 'success'}
        return res
        
            
    def download(self, filename):
        #TODO
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
            dataset = image_ID
            result_dict_path = os.path.join(self.path, f'result/he/path_map.json')
            with open(result_dict_path, 'r') as json_file:
                result_dict = json.load(json_file)
            keys_array = list(result_dict.keys())
            if dataset:
                if dataset in result_dict:
                    he_img_path = os.path.join(self.path, result_dict[dataset]["pic_path"])
                    return he_img_path
                else:
                    return ""
            else:
                if keys_array:
                    first_key = keys_array[0]
                    he_img_path = os.path.join(self.path, result_dict[first_key]["pic_path"])
                    return he_img_path
                else:
                    return ""
        else:
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

    
    def _find_cellchat_rds(self, dataset):
        """根据 dataset (UUID) 定位 subtask_cellchat 的 RDS 文件"""
        if getattr(self, '_is_demo', False):
            rds_files = glob.glob(os.path.join(self.path, 'result', 'cellchat', '*.rds'))
            return rds_files[0] if rds_files else None
        if not dataset:
            raise ValueError('dataset is required')
        rds_path = os.path.join(self.path, f'dataset_{dataset}', 'subtask_cellchat', 'result', 'cellchat_result.rds')
        if os.path.exists(rds_path):
            return rds_path
        # dataset 可能是 DB 的 dataset_id, 但磁盘目录用的是 title(UUID)
        # 尝试查 DB 转换
        try:
            db_obj = Dataset.objects.filter(dataset_id=dataset).first()
            if db_obj:
                rds_path = os.path.join(self.path, f'dataset_{db_obj.title}', 'subtask_cellchat', 'result', 'cellchat_result.rds')
                if os.path.exists(rds_path):
                    return rds_path
        except Exception:
            pass
        return None

    def getCellChatPathways(self, dataset=None):
        rds_path = self._find_cellchat_rds(dataset)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_pathways(rds_path)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatCircleData(self, pathway, dataset=None):
        rds_path = self._find_cellchat_rds(dataset)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_circle(rds_path, signaling=pathway)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatSpatialData(self, pathway, dataset=None):
        rds_path = self._find_cellchat_rds(dataset)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_spatial(rds_path, signaling=pathway)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatHeatmapData(self, LR_pair, dataset=None):
        rds_path = self._find_cellchat_rds(dataset)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_heatmap(rds_path, lrpair=LR_pair)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatLRPairs(self, dataset=None):
        rds_path = self._find_cellchat_rds(dataset)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_pairLRs(rds_path)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getSpiderInit(self):
        """
        SPIDER 接口1：初始化，返回 Metadata 和 Coordinates
        """
        h5ad_path = os.path.join(self.path, 'result/spider/adata_spider.h5ad')
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

    def getSpiderPatternData(self, pattern_id):
        """
        SPIDER 接口2：获取指定 Pattern 的评分
        """
        h5ad_path = os.path.join(self.path, 'result/spider/adata_spider.h5ad')
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

    def getSpiderLRData(self, lr_name):
        """
        SPIDER 接口3：获取指定 LR 的表达量
        """
        h5ad_path = os.path.join(self.path, 'result/spider/adata_spider.h5ad')
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

    def getSpiderSpearmanData(self):
        sc_path = os.path.join(self.path, 'result/spider/spearman/lr_level_spearman_correlation_sc.csv')
        sc_st_path = os.path.join(self.path, 'result/spider/spearman/lr_level_spearman_correlation_sc_st.csv')
        
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
            return self.getLRPairs(query_params.get('dataset'))
        elif resulttype == 'LRreceivedSignalStrength':
            return self.getReceivedSignalStrength(query_params.get('dataset'), query_params.get('lr_pair'))
        elif resulttype == 'networkData':
            return self.getNetworkData(query_params.get('dataset'), query_params.get('type'))
        elif resulttype == 'img_path':
            return self.getImgpath(query_params.get('analysis_type'), query_params.get('img_id'))
        elif resulttype == 'cellchat_pathways':
            return self.getCellChatPathways(query_params.get('dataset'))
        elif resulttype == 'cellchat_circle':
            return self.getCellChatCircleData(query_params.get('pathway'), query_params.get('dataset'))
        elif resulttype == 'cellchat_spatial':
            return self.getCellChatSpatialData(query_params.get('pathway'), query_params.get('dataset'))
        elif resulttype == 'cellchat_heatmap':
            return self.getCellChatHeatmapData(query_params.get('LR_pair'), query_params.get('dataset'))
        elif resulttype == 'cellchat_lrpairs':
            return self.getCellChatLRPairs(query_params.get('dataset'))
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
            return self.getLRPairs(query_params.get('dataset'))
        elif resulttype == 'LRreceivedSignalStrength':
            return self.getReceivedSignalStrength(query_params.get('dataset'), query_params.get('lr_pair'))
        elif resulttype == 'cellchat_pathways':
            return self.getCellChatPathways()
        elif resulttype == 'cellchat_circle':
            return self.getCellChatCircleData(query_params.get('pathway'))
        elif resulttype == 'cellchat_spatial':
            return self.getCellChatSpatialData(query_params.get('pathway'))
        elif resulttype == 'cellchat_heatmap':
            return self.getCellChatHeatmapData(query_params.get('LR_pair'))
        elif resulttype == 'cellchat_lrpairs':
            return self.getCellChatLRPairs()
        elif resulttype == 'spider_init':
            # 获取元数据和坐标
            return self.getSpiderInit()
            
        elif resulttype == 'spider_pattern':
            # 获取特定 Pattern 的数值
            return self.getSpiderPatternData(query_params.get('pattern_id'))
            
        elif resulttype == 'spider_lr':
            # 获取特定 LR 的数值
            return self.getSpiderLRData(query_params.get('lr_name'))
        elif resulttype == 'spider_spearman':
            # --- 新增：Spearman 分析数据接口 ---
            return self.getSpiderSpearmanData()
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
        
class SubScstquery(Module):
    def __init__(self, subtask_type, root_dir, dataset_path, params):
        # 自理目录：/user_dir/dataset_path/subtask_name
        self.params = params
        self.subtask_type = subtask_type
        userid = params['userid']  # 假设传 userid（或从 main_userpath 解析）
        super().__init__(name='scst_subtask', userpath=root_dir)  # 基类会 prepend USERTASKPATH
        user_main_dir = self.path  # USERTASKPATH + root_dir
        print("user_main_dir", user_main_dir)
        dataset_id = None
        if dataset_path:
            # 1. 以 '/' 分割路径
            path_parts = dataset_path.split('/')
            
            # 2. 移除空字符串（例如，路径以 / 开头或结尾）
            path_parts = [part for part in path_parts if part] 

            if len(path_parts) >= 3:
                # 倒数第三个元素的索引是 -3
                dataset_id = path_parts[-3]
            else:
                # 路径格式不符合预期，可以记录错误
                print(f"ERROR: Cannot extract dataset_id from path: {dataset_path}")
                # 返回失败或使用默认值，取决于业务需求
        
        sub_dir = f"dataset_{dataset_id}/subtask_{subtask_type.replace(' ', '_')}"  # e.g., "dataset_102/xx1"
        self.path = os.path.join(user_main_dir, sub_dir)
        print(self.path)
        os.makedirs(self.path, exist_ok=True)  # 创建用户目录
        # os.makedirs(self.path + '/upload/', exist_ok=True)  # 创建子 upload
        
        # 确保子任务目录结构存在
        os.makedirs(os.path.join(self.path, 'upload'), exist_ok=True)
        os.makedirs(os.path.join(self.path, 'result'), exist_ok=True)


        # 2. 关键：数据继承/文件复制
        # 假设主任务的输入文件位于：主任务路径/upload/input.h5ad
        main_input_h5ad_path = os.path.join(user_main_dir, 'upload/input.h5ad') 
        # sub_h5ad_path = os.path.join(self.path, 'upload/input.h5ad')

        # 小种类区分（if-else）, TODO 不同种类的把不同的脚本路径和参数写入self.shell_script, self.script_arguments中
        sub_type = params.get('sub_type', 'default')
        # inputfilepath = self.path + '/upload/input.h5ad'
        inputfilepath = main_input_h5ad_path
        outputdir = self.path + '/result/'
        projectname = params.get('projectname', 'default')
        organs = params.get('organParts', '')
        if subtask_type == 'hierarchical':
            self.script_arguments = [inputfilepath, outputdir, projectname, '190', '1.2', 'hierarchical', organs]
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/sub_hierarchical.sh'
        elif subtask_type in ('recall_analysis', 'annotation_mapping'):
            self.shell_script = local_settings.SCDB_MODULE + 'noop.sh'
            self.script_arguments = []
        elif subtask_type == 'hierarchical_clustering':
            self.script_arguments = [
                inputfilepath,
                outputdir,
                projectname + '_hierarchical',
                '190',
                '1.2',
                'cell_type',
                'true',
                organs,
            ]
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/run.sh'
        elif subtask_type == 'marker_genes':
            self.script_arguments = [inputfilepath, outputdir, params.get('gene', 'default_gene'), 'marker_only']
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/sub_marker.sh'
        elif subtask_type == "commot":
            scst_h5adpath = "/data3/platform/sc_db/scgpt/data/cellxgene/st/lung/dfbedaf2-1af4-416c-b63a-d6af65a851f8.h5ad" # $1: TODO 改成sc-st文件路径
            self.script_arguments = [
                scst_h5adpath,
                outputdir
            ]
            self.shell_script = "/data3/platform/sc_db/commot/run_commot.sh"
        elif subtask_type == "cellchat":
            # 1. 提取参数 (使用 params.get 设置默认值，与 R 脚本保持逻辑一致)
            groupby = params.get('groupby', 'cell_type')
            
            # 注意：前端可能传 'signaling'，对应 R 的 db_mode
            db_mode = params.get('db_mode', 'Secreted Signaling') 
            
            # 新增参数
            datatype = params.get('datatype', 'sc')        # sc 或 st
            min_cells = params.get('min_cells', 10)        # 整数
            contact_range = params.get('contact_range', 100) # ST专用
            scale_distance = params.get('scale_distance', 50) # ST专用

            output_filepath = os.path.join(outputdir, "cellchat_result.rds")
            
            self.script_arguments = [
                "/data3/platform/sc_db/scgpt/data/cellxgene/st/lung/dfbedaf2-1af4-416c-b63a-d6af65a851f8.h5ad", # $1: TODO 改成sc-st文件路径
                output_filepath,      # $2: Output (建议把输出放前面，逻辑更顺)
                groupby,              # $3: Groupby
                db_mode,              # $4: DB Mode
                datatype,             # $5: Datatype
                str(min_cells),       # $6: Min Cells (转字符串)
                str(contact_range),   # $7: Contact Range
                str(scale_distance)   # $8: Scale Distance
            ]
            
            print(f"CellChat Args: {self.script_arguments}")
            
            self.shell_script = "/data3/platform/sc_db/cellchat/run_slurm_cellchat.sh"
        else:
            raise ValueError(f"不支持的小种类: {subtask_type}")

    def process(self):
        if self.subtask_type in ('recall_analysis', 'annotation_mapping'):
            if self.dependencies:
                return super().process()
            self.status = 'Completed'
            self.job_id = 'viewer_only'
            return self.job_id
        if self.subtask_type == 'hierarchical_clustering':
            output_check = os.path.join(self.path, 'result/he/HierarchicalClustering')
            if os.path.isdir(output_check) and os.listdir(output_check):
                self.status = 'Completed'
                self.job_id = 'skipped_existing'
                return self.job_id
        return super().process()

    def getresult(self, query_params):
        sub_type = self.params.get('sub_type', 'default')
        resulttype = query_params.get('resulttype')
        if sub_type == 'hierarchical':
            if resulttype == 'hierarchicalClusteringMarkerGenes':
                return self.getHierarchicalClusteringMarkerGenes(query_params.get('dataset'), query_params.get('cluster'))
        elif sub_type == 'marker_genes':
            if resulttype == 'markerExpression':
                # 自定义
                return {'results': '标记基因数据', 'status': 'success'}
        # 默认或复用基类（如果有通用）
        else:
            expressionfile = self.path + '/result/scquery/sc_output_expression.csv'
            if os.path.exists(expressionfile):
                expression = pd.read_csv(expressionfile, index_col=0)
                return {'results': expression.to_dict(orient='records')}
            return {'error': '结果文件不存在'}

    # ... 加其他方法如 getmetaresult 等