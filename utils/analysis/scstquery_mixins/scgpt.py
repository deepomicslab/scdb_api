import os
from dataset.models import Dataset


class ScgptMixin:
    """scGPT embedding result methods for Scstquery.

    The scgpt_embedding subtask produces two PNG images (UMAP + heatmap sorted
    by cell type) under dataset_{uuid}/subtask_scgpt_embedding/result/; both are
    streamed back as files (see _stream_file handling in taskresultview).
    """

    def _resolve_scgpt_dir(self, dataset_id):
        if not dataset_id:
            return None
        try:
            ds = Dataset.objects.get(dataset_id=dataset_id)
            uuid = ds.title
            base = os.path.join(self.path, f'dataset_{uuid}', 'subtask_scgpt_embedding', 'result')
            if os.path.isdir(base):
                return base
        except Dataset.DoesNotExist:
            pass
        return None

    def _scgpt_image_file(self, dataset_id, filename):
        base = self._resolve_scgpt_dir(dataset_id)
        if not base:
            return None
        path = os.path.join(base, filename)
        return path if os.path.isfile(path) else None

    def getScgptUmap(self, dataset):
        path = self._scgpt_image_file(dataset, 'cell_embeddings_umap.png')
        if not path:
            return {'status': 'fail', 'message': f'scGPT UMAP image not found for dataset {dataset}'}
        return {'_image_file': path}

    def getScgptHeatmap(self, dataset):
        path = self._scgpt_image_file(dataset, 'cell_embeddings_heatmap_sorted_by_celltype.png')
        if not path:
            return {'status': 'fail', 'message': f'scGPT heatmap image not found for dataset {dataset}'}
        return {'_image_file': path}
