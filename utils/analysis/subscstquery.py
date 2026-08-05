import os
import pandas as pd
from scdb_api import settings_local as local_settings
from utils.mapping_paths import resolve_mapping_output_path
from task.models import TaskStatus, SubTask
from .base import Module
import utils.slurm_api as slurm_api


class SubScstquery(Module):
    def __init__(self, subtask_type, root_dir, dataset_uuid, dataset_path, st_h5ad_path, params):
        # Self-managed directory: /user_dir/dataset_path/subtask_name
        self.params = params
        self.subtask_type = subtask_type
        self.dataset_uuid = dataset_uuid
        self._dataset_path = dataset_path
        userid = params['userid']  # assumes userid is passed (or parse from main_userpath)
        super().__init__(name='scst_subtask', userpath=root_dir)  # the base class prepends USERTASKPATH
        user_main_dir = self.path  # USERTASKPATH + root_dir
        self.user_main_dir = user_main_dir

        if dataset_uuid:
            sub_dir = f"dataset_{dataset_uuid}/subtask_{subtask_type.replace(' ', '_')}"
            self.path = os.path.join(user_main_dir, sub_dir)
            os.makedirs(self.path, exist_ok=True)
            os.makedirs(os.path.join(self.path, 'upload'), exist_ok=True)
            os.makedirs(os.path.join(self.path, 'result'), exist_ok=True)



        # 2. Key: data inheritance / file copy
        # The main task's input file is at: main task path/upload/input.h5ad
        main_input_h5ad_path = os.path.join(user_main_dir, 'upload/input.h5ad') 
        # sub_h5ad_path = os.path.join(self.path, 'upload/input.h5ad')

        # Subtask type dispatch (if-else); TODO: write the per-type script path
        # and arguments into self.shell_script, self.script_arguments
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
            groupby = params.get('groupby', 'cell_type')
            db_mode = params.get('db_mode', 'all')
            datatype = params.get('datatype', 'st')
            min_cells = params.get('min_cells', 10)
            zero_dist_handle = params.get('zero_dist_handle', 'jitter')
            cellchat_type = params.get('type', 'truncatedMean')
            trim = str(params.get('trim', 0.1))
            interaction_range = str(params.get('interaction_range', 250))

            mapping_method = self.params.get('mapping_method', 'cytospace')
            if datatype == 'sc':
                outputdir = os.path.join(self.path, 'result', 'sc', '')
            else:
                outputdir = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, '')
            os.makedirs(outputdir, exist_ok=True)
            output_filepath = os.path.join(outputdir, "cellchat_result.rds")

            mapping_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)
            self.script_arguments = [
                mapping_h5ad,
                output_filepath,
                groupby,
                db_mode,
                datatype,
                str(min_cells),
                zero_dist_handle,
                cellchat_type,
                cellchat_type,
                trim,
                interaction_range,
                'FALSE',
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
            species = params.get('species', 'human').capitalize()
            mapping_method = self.params.get('mapping_method', 'cytospace')
            mapping_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)
            outputdir = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, '')
            os.makedirs(outputdir, exist_ok=True)
            self.script_arguments = [
                mapping_h5ad,
                outputdir,
                species,
            ]
            self.shell_script = local_settings.ALPHATALK_SCRIPT
        elif subtask_type == "lr_comparison":
            species = params.get('species', 'human').capitalize()
            mapping_method = self.params.get('mapping_method', 'cytospace')
            cluster_key = params.get('groupby', 'cell_type')
            db_mode = params.get('db_mode', 'secreted')
            min_cells = str(params.get('min_cells', 10))
            zero_dist_handle = params.get('zero_dist_handle', 'jitter')
            sc_type = params.get('sc_type', 'triMean')
            st_type = params.get('st_type', 'truncatedMean')
            trim = str(params.get('trim', 0.1))
            interaction_range = str(params.get('interaction_range', 250))
            population_size = str(params.get('population_size', False))

            self._lr_species = species
            self._lr_mapping_method = mapping_method
            self._lr_cluster_key = cluster_key
            self._lr_cellchat_params = {
                'groupby': cluster_key,
                'db_mode': db_mode,
                'min_cells': min_cells,
                'zero_dist_handle': zero_dist_handle,
                'sc_type': sc_type,
                'st_type': st_type,
                'trim': trim,
                'interaction_range': interaction_range,
                'population_size': population_size,
            }

            # Output path: SC CellChat
            cellchat_base = os.path.join(user_main_dir, f'dataset_{dataset_uuid}', 'subtask_cellchat', 'result')
            self._sc_cellchat_rds = os.path.join(cellchat_base, 'sc', 'cellchat_result.rds')
            self._sc_cellchat_exists = os.path.exists(self._sc_cellchat_rds)

            # Output path: SC+ST CellChat
            self._st_cellchat_rds = os.path.join(cellchat_base, 'sc_st_mapping', mapping_method, 'cellchat_result.rds')
            self._st_cellchat_exists = os.path.exists(self._st_cellchat_rds)

            # Postprocess output path
            # Note: the shell script run_lr_comparison_postprocess.sh appends another
            # "spearman" layer under OUTPUT_DIR as the output directory of
            # spearman_down_stream_gene.py, so only the result root is passed here,
            # avoiding a result/spearman/spearman double path (kept consistent with
            # the backend getLRSpearmanData read path).
            lr_base = os.path.join(self.path, 'result')
            self._sc_spearman_dir = os.path.join(lr_base, '')
            self._st_spearman_dir = os.path.join(lr_base, 'sc_st_mapping', mapping_method, '')
            os.makedirs(lr_base, exist_ok=True)
            os.makedirs(os.path.join(lr_base, 'sc_st_mapping', mapping_method), exist_ok=True)

            # Input data
            self._sc_input_h5ad = main_input_h5ad_path
            self._st_input_h5ad = self._resolve_mapping_output(self.dataset_uuid, mapping_method)

            self.shell_script = None  # process() calls submit_job directly
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
            raise ValueError(f"Unsupported subtask type: {subtask_type}")

    def _check_running_cellchat(self):
        from django.db.models import Q
        # SubTask.dataset_path stores the dataset_id (see services.create_subtask),
        # so filter by the dataset_id in params, not the marker path
        running = SubTask.objects.filter(
            main_task__userpath=self.user_main_dir.replace(local_settings.USERTASKPATH, ''),
            subtask_type='cellchat',
            dataset_path=self.params.get('dataset_id', ''),
        ).filter(
            Q(status__iexact='created') | Q(status__iexact='pending') | Q(status__iexact='running')
        ).first()
        if running:
            raise ValueError(
                f"CellChat subtask (id={running.id}) is still running. "
                "Please wait for it to complete before running LR Pair Comparison."
            )

    def _resolve_mapping_output(self, dataset_uuid, mapping_method='cytospace'):
        return resolve_mapping_output_path(self.user_main_dir, str(dataset_uuid), mapping_method)


    def process(self):
        if self.subtask_type == 'lr_comparison':
            cellchat_script = "/data3/platform/sc_db/cellchat/run_slurm_cellchat.sh"
            postprocess_script = getattr(local_settings, 'LR_COMPARISON_POSTPROCESS_SCRIPT', None)

            dependency_job_ids = []

            # 1. SC CellChat
            if not self._sc_cellchat_exists:
                sc_outputdir = os.path.dirname(self._sc_cellchat_rds)
                os.makedirs(sc_outputdir, exist_ok=True)
                cc = self._lr_cellchat_params
                sc_args = [
                    self._sc_input_h5ad,      # $1: input h5ad
                    self._sc_cellchat_rds,     # $2: output rds
                    cc['groupby'],             # $3: groupby
                    cc['db_mode'],             # $4: db_mode
                    'sc',                      # $5: datatype
                    cc['min_cells'],           # $6: min_cells
                    cc['zero_dist_handle'],    # $7: zero_dist_handle
                    cc['sc_type'],             # $8: sc_type
                    cc['st_type'],             # $9: st_type
                    cc['trim'],                # $10: trim
                    cc['interaction_range'],   # $11: interaction_range
                    cc['population_size'],     # $12: population_size
                ]
                sc_job_id = slurm_api.submit_job(cellchat_script, sc_args)
                self.params['_sc_cellchat_job_id'] = sc_job_id
                dependency_job_ids.append(sc_job_id)
            else:
                self.params['_sc_cellchat_job_id'] = None

            # 2. SC+ST CellChat
            if not self._st_cellchat_exists:
                self._check_running_cellchat()
                st_outputdir = os.path.dirname(self._st_cellchat_rds)
                os.makedirs(st_outputdir, exist_ok=True)
                cc = self._lr_cellchat_params
                st_args = [
                    self._st_input_h5ad,       # $1: input h5ad (mapping output)
                    self._st_cellchat_rds,     # $2: output rds
                    cc['groupby'],             # $3: groupby
                    cc['db_mode'],             # $4: db_mode
                    'st',                      # $5: datatype
                    cc['min_cells'],           # $6: min_cells
                    cc['zero_dist_handle'],    # $7: zero_dist_handle
                    cc['sc_type'],             # $8: sc_type
                    cc['st_type'],             # $9: st_type
                    cc['trim'],                # $10: trim
                    cc['interaction_range'],   # $11: interaction_range
                    cc['population_size'],     # $12: population_size
                ]
                st_job_id = slurm_api.submit_job(cellchat_script, st_args)
                self.params['_st_cellchat_job_id'] = st_job_id
                dependency_job_ids.append(st_job_id)
            else:
                self.params['_st_cellchat_job_id'] = None

            # 3. Combined post-processing
            post_args = [
                self._sc_input_h5ad,          # $1: SC h5ad
                self._sc_cellchat_rds,        # $2: SC rds
                self._st_input_h5ad,          # $3: ST h5ad
                self._st_cellchat_rds,        # $4: ST rds
                self._sc_spearman_dir,        # $5: SC spearman output directory
                self._st_spearman_dir,        # $6: ST spearman output directory
                self._lr_cluster_key,         # $7: cluster_key
            ]
            post_job_id = slurm_api.submit_job(
                postprocess_script, post_args,
                dependency_job_ids=dependency_job_ids if dependency_job_ids else None
            )

            self.job_id = post_job_id
            self.status = TaskStatus.RUNNING
            return self.job_id

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
                # custom
                return {'results': 'Marker gene data', 'status': 'success'}
        # Default: reuse the base class (if there is a generic one)
        else:
            expressionfile = self.path + '/result/scquery/sc_output_expression.csv'
            if os.path.exists(expressionfile):
                expression = pd.read_csv(expressionfile, index_col=0)
                return {'results': expression.to_dict(orient='records')}
            return {'error': 'Result file not found'}
