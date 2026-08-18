import os
import json
import pandas as pd
import scanpy as sc
from pathlib import Path
from scdb_api import settings_local as local_settings
from utils.page import paginate_dataframe
from dataset.models import Dataset
from utils.logging import get_logger

logger = get_logger('mixin_common')


# Bare-filename compatibility layer for the legacy filelist contract: the current
# frontend (useFileList / legacy Scquery pages) sends plain names without a directory,
# so they are looked up in these result directories. Relative paths that contain a
# separator are instead resolved against the whole task root (self.path), which lets
# subtask results (dataset_{uuid}/subtask_{type}/result/...) be downloaded without
# extending this list.
_DOWNLOAD_BARE_DIRS = (
    'result/sc_marker',
    'result/sc_query/annotation_h5ad',
    'result/meta',
)

# Server-internal metadata that must never be downloadable: they embed absolute server
# paths / serialized module objects and would leak the same info the platform otherwise
# sanitizes (path de-identification, "never store server paths").
_DOWNLOAD_EXCLUDED = {
    'taskdetail.json',
    'moduleobject.pkl',
}


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

        # Batch-resolve every matched dataset title in ONE query instead of one
        # query per dataset (N+1): collect all uuids across organs, then look them
        # up in an in-memory dict. Semantics match filter(title=x).first() since
        # Dataset.title is unique.
        all_uuids = set()
        for datasets_dict in raw_data.values():
            for original_path in datasets_dict:
                u = self._extract_dataset_uuid(original_path)
                if u:
                    all_uuids.add(u)
        by_title = {d.title: d for d in Dataset.objects.filter(title__in=all_uuids)}

        for organ_name, datasets_dict in raw_data.items():
            transformed_data[organ_name] = {}
            
            for original_path, scores in datasets_dict.items():
                extracted_uuid = self._extract_dataset_uuid(original_path) or ""

                db_obj = by_title.get(extracted_uuid) if extracted_uuid else None

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
                # Note: do not send server paths (original_path / file_path) to the frontend;
                # the frontend only uses dataset_id; when a path is needed, the backend
                # resolves it via resolve_marker_path.
                new_value['title'] = new_key
                new_value['description'] = description
                new_value['meta'] = meta_info
                # Image presence (hires.jpg cache check): the frontend uses this to skip
                # getImg requests, avoiding no-image 404s spamming the logs
                if db_obj:
                    new_value['has_image'] = db_obj.has_image()
                    # Precomputed Original ST results availability (per tool):
                    # the frontend enables/disables the "ST Reference" view entry
                    new_value['st_precomputed'] = {
                        'commot': bool(db_obj.precomputed_commot_path),
                        'cellchat': bool(db_obj.precomputed_cellchat_path),
                        'spider': bool(db_obj.precomputed_spider_path),
                        'alphatalk': bool(db_obj.precomputed_alphatalk_path),
                    }

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

        # The frontend only sends dataset_id; server paths are resolved by the backend
        # and are never sent to / accepted from the client
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
        """Read a file from the task workspace and return it base64-encoded (legacy JSON contract).

        The download boundary is the whole task directory (self.path): any relative path
        inside it can be fetched, so subtask results under dataset_{uuid}/subtask_*/result/
        are supported without extra whitelisting. Bare filenames (no separator) keep the old
        filelist behavior and are looked up in _DOWNLOAD_BARE_DIRS.

        Safety: rejects absolute paths, ".." traversal, and symlinks that resolve outside
        the task root; server-internal metadata files are excluded.
        """
        # 1. Basic sanity: non-empty, not absolute, no ".." segments, no backslashes
        if not filename or os.path.isabs(filename) or '\\' in filename:
            return {'status': 'fail', 'message': 'Invalid filename.'}
        parts = filename.split('/')
        if any(p in ('', '.', '..') for p in parts):
            return {'status': 'fail', 'message': 'Invalid filename.'}
        # never expose server-internal metadata
        if parts[-1] in _DOWNLOAD_EXCLUDED:
            return {'status': 'fail', 'message': 'Invalid filename.'}

        task_root = os.path.realpath(self.path)

        # 2. Resolve candidates: bare names search the legacy dirs, paths with separators
        #    resolve directly against the task root.
        if '/' in filename:
            candidates = [os.path.join(task_root, filename)]
        else:
            candidates = [os.path.join(task_root, d, filename) for d in _DOWNLOAD_BARE_DIRS]

        for candidate in candidates:
            real = os.path.realpath(candidate)
            # containment guard: final path must stay inside the task root (blocks symlink escape)
            if os.path.commonpath([task_root, real]) != task_root:
                continue
            if not os.path.isfile(real):
                continue
            try:
                with open(real, 'rb') as f:
                    file_content = f.read()
                    import base64
                    file_content_base64 = base64.b64encode(file_content).decode('utf-8')
                    return {
                        'filename': filename,
                        'file_content': file_content_base64,
                        'status': 'success',
                        'message': "read file successfully.",
                    }
            except Exception as e:
                logger.warning('Error reading file %s: %s', filename, e)
                return {'status': 'fail', 'message': "File cannot be read."}

        logger.info('File %s does not exist in the task workspace', filename)
        return {'status': 'fail', 'message': "File is not existed."}
    
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
                logger.info('Directory %s does not exist.', input_dir_path)
        elif flag == "output":
            filelist['h5ad'] = []
            output_h5ad_dir_path = os.path.join(self.path, 'result/sc_query/annotation_h5ad')
            if os.path.exists(output_h5ad_dir_path):
                for file in os.listdir(output_h5ad_dir_path):
                    if file.endswith('.h5ad'):
                        filelist['h5ad'].append(file)
            else:
                logger.info('Directory %s does not exist.', output_h5ad_dir_path)
            
            filelist['meta'] = []
            output_meta_dir_path = os.path.join(self.path, 'result/meta')
            if os.path.exists(output_meta_dir_path):
                for file in os.listdir(output_meta_dir_path):
                    if file.endswith('_meta_data_addquerycell.txt'):
                        filelist['meta'].append(file)
            else:
                logger.info('Directory %s does not exist.', output_meta_dir_path)
        else:
            res = {'status': 'fail', 'message': "Wrong filelist type."}
            return res
        res = {'filelist': filelist, 'flag': flag, 'status': 'success'}
        return res
