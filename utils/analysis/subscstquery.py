import os
import pandas as pd
from scdb_api import settings_local as local_settings
from utils.mapping_paths import resolve_mapping_output_path
from task.models import TaskStatus
from .base import Module


class SubScstquery(Module):
    def __init__(self, subtask_type, root_dir, dataset_uuid, dataset_path, st_h5ad_path, params):
        # 自理目录：/user_dir/dataset_path/subtask_name
        self.params = params
        self.subtask_type = subtask_type
        self.dataset_uuid = dataset_uuid
        userid = params['userid']  # 假设传 userid（或从 main_userpath 解析）
        super().__init__(name='scst_subtask', userpath=root_dir)  # 基类会 prepend USERTASKPATH
        user_main_dir = self.path  # USERTASKPATH + root_dir
        self.user_main_dir = user_main_dir
        print("user_main_dir", user_main_dir)

        if dataset_uuid:
            sub_dir = f"dataset_{dataset_uuid}/subtask_{subtask_type.replace(' ', '_')}"
            self.path = os.path.join(user_main_dir, sub_dir)
            print(self.path)
            os.makedirs(self.path, exist_ok=True)
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
        elif subtask_type == 'annotation_mapping':
            # annotation_mapping is now a routing-only subtask; actual work delegated to he_scatter
            self.script_arguments = []
            self.shell_script = None  # no SLURM job; he_scatter handles the actual work
        elif subtask_type == 'he_scatter':
            output_json = os.path.join(user_main_dir, 'result/sc_query/output.json')
            projectname = params.get('projectname', 'default')
            hc_csv = os.path.join(user_main_dir, 'result/sc_marker', f'{projectname}_hierarchical_clusters.csv')
            if os.path.exists(hc_csv):
                celltype_count_dic = hc_csv
            else:
                celltype_count_dic = os.path.join(user_main_dir, 'result/sc_marker', f'{projectname}_clusters.csv')
            self.script_arguments = [output_json, dataset_path, outputdir, celltype_count_dic]
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/sub_he_scatter.sh'
        elif subtask_type == 'recall_analysis':
            pass  # viewer type, data served by hierarchical_clustering subtask
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
                dataset_path,
            ]
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/sub_hierarchical_clustering.sh'
        elif subtask_type == 'marker_genes':
            self.script_arguments = [inputfilepath, outputdir, params.get('gene', 'default_gene'), 'marker_only']
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/sub_marker.sh'
        elif subtask_type == "commot":
            mapping_method = self.params.get('mapping_method', 'cytospace')
            mapping_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)
            outputdir = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, '')
            os.makedirs(outputdir, exist_ok=True)
            signaling_type = params.get('signaling_type', 'Secreted Signaling')
            dis_thr = str(params.get('dis_thr', 500))
            min_cell_pct = str(params.get('min_cell_pct', 0.05))
            n_permutations = str(params.get('n_permutations', 100))
            self.script_arguments = [
                mapping_h5ad,
                outputdir,
                signaling_type,
                dis_thr,
                min_cell_pct,
                n_permutations
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
            zero_dist_handle = params.get('zero_dist_handle', 'jitter')  # ST only

            mapping_method = self.params.get('mapping_method', 'cytospace')
            if datatype == 'sc':
                outputdir = os.path.join(self.path, 'result', 'sc', '')
            else:
                outputdir = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, '')
            os.makedirs(outputdir, exist_ok=True)
            output_filepath = os.path.join(outputdir, "cellchat_result.rds")
            
            mapping_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)
            self.script_arguments = [
                mapping_h5ad,          # $1: input h5ad (mapping output)
                output_filepath,      # $2: Output (建议把输出放前面，逻辑更顺)
                groupby,              # $3: Groupby
                db_mode,              # $4: DB Mode
                datatype,             # $5: Datatype
                str(min_cells),       # $6: Min Cells (转字符串)
                str(contact_range),   # $7: Contact Range
                str(scale_distance),  # : Scale Distance (auto-calculated in R)
                zero_dist_handle     # : Same-spot cell handling
            ]
            
            print(f"CellChat Args: {self.script_arguments}")
            
            self.shell_script = "/data3/platform/sc_db/cellchat/run_slurm_cellchat.sh"
        elif subtask_type == "spider":
            species = params.get('species', 'human')
            datatype_val = params.get('datatype', 'st')
            cluster_key = params.get('groupby', 'cell_type')
            p_value = params.get('p_value', 0.05)
            is_human = 'True' if species == 'human' else 'False'
            is_sc = 'True' if datatype_val == 'sc' else 'False'

            mapping_method = self.params.get('mapping_method', 'cytospace')
            mapping_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)
            outputdir = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, '')
            os.makedirs(outputdir, exist_ok=True)
            self.script_arguments = [
                mapping_h5ad,
                outputdir,
                is_human,
                is_sc,
                cluster_key,
                str(p_value)
            ]
            self.shell_script = local_settings.SCDB_MODULE + 'scst_query/sub_spider.sh'
        elif subtask_type == "alphatalk":
            species = params.get('species', 'human')
            species_cap = 'Human' if species == 'human' else 'Mouse'
            mapping_method = self.params.get('mapping_method', 'cytospace')
            mapping_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)
            outputdir = os.path.join(self.path, 'result', 'alphatalk', '')
            os.makedirs(outputdir, exist_ok=True)
            self.script_arguments = [
                mapping_h5ad,
                outputdir,
                species_cap,
            ]
            self.shell_script = "/data3/platform/sc_db/AlphaTalk/run_slurm_alphatalk.sh"
        elif self.subtask_type == 'scst_mapping':
            mapping_method = self.params.get('mapping_method', 'cytospace')
            if mapping_method == 'cytospace':
                self.shell_script = local_settings.CYTOSPACE_SCRIPT
            elif mapping_method == 'tangram':
                self.shell_script = local_settings.TANGRAM_SCRIPT
            else:
                raise ValueError(f"Unknown mapping_method: {mapping_method}")
            method_outputdir = os.path.join(outputdir, mapping_method)
            os.makedirs(method_outputdir, exist_ok=True)
            if mapping_method == 'tangram':
                tg_mode = params.get('mode', 'cells')
                tg_cluster_label = params.get('cluster_label', 'cell_type')
                tg_target_count = str(params.get('target_count', 5000))
                self.script_arguments = [inputfilepath, st_h5ad_path, method_outputdir, tg_mode, tg_cluster_label, tg_target_count]
            elif mapping_method == 'cytospace':
                cs_mcn = str(params.get('mean_cell_numbers', 2))
                cs_dm = params.get('distance_metric', 'Pearson_correlation')
                self.script_arguments = [inputfilepath, st_h5ad_path, method_outputdir, cs_mcn, cs_dm]
            else:
                self.script_arguments = [inputfilepath, st_h5ad_path, method_outputdir]
        else:
            raise ValueError(f"不支持的小种类: {subtask_type}")

    def _resolve_mapping_output(self, dataset_uuid, mapping_method='cytospace'):
        return resolve_mapping_output_path(self.user_main_dir, str(dataset_uuid), mapping_method)


    def process(self):
        if self.subtask_type == 'recall_analysis':
            if self.dependencies:
                self.status = TaskStatus.PENDING
                self.job_id = 'pending_hc'
                return self.job_id
            self.status = TaskStatus.COMPLETED
            self.job_id = 'viewer_only'
            return self.job_id
        if self.subtask_type == 'annotation_mapping':
            # routing-only; actual work delegated to he_scatter
            if self.dependencies:
                self.status = TaskStatus.PENDING
                self.job_id = 'pending_he_scatter'
                return self.job_id
            self.status = TaskStatus.COMPLETED
            self.job_id = 'viewer_only'
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
