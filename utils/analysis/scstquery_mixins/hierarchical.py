import os
import numpy as np
import pandas as pd
from collections import OrderedDict


# gene_expression.csv parse cache: mtime-aware + LRU capped at 2 files.
# First read of the 408MB CSV takes ~20s; once cached, all subsequent
# markerGenes / markerGeneExpressions requests for the same task hit directly (~0.1s).
_gene_expression_cache = OrderedDict()
_GENE_EXPRESSION_CACHE_MAX = 2


def _load_gene_expression(expression_file_path):
    """Read gene_expression.csv (mtime-aware cache). Returns DataFrame or None."""
    if not os.path.exists(expression_file_path):
        return None
    try:
        mtime = os.path.getmtime(expression_file_path)
    except OSError:
        return None
    cached = _gene_expression_cache.get(expression_file_path)
    if cached and cached[0] == mtime:
        _gene_expression_cache.move_to_end(expression_file_path)
        return cached[1]
    df = pd.read_csv(expression_file_path, index_col=0)
    _gene_expression_cache[expression_file_path] = (mtime, df)
    _gene_expression_cache.move_to_end(expression_file_path)
    while len(_gene_expression_cache) > _GENE_EXPRESSION_CACHE_MAX:
        _gene_expression_cache.popitem(last=False)
    return df


class HierarchicalClusteringMixin:
    """Hierarchical clustering result methods for Scstquery."""

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
        expression_df = _load_gene_expression(expression_file_path)
        if expression_df is None:
            return {'status': 'fail', 'message': f'File not found: {expression_file_path}'}
        HierarchicalClustering_result_dir_path = os.path.join(base, 'HierarchicalClustering/')
        file_name = "cluster" + cluster.replace(" ", "_") + "_merged_data_with_labels.csv"
        cluster_file_path = os.path.join(HierarchicalClustering_result_dir_path, file_name)
        if not os.path.exists(cluster_file_path):
            return {'status': 'fail', 'message': f'File not found: {cluster_file_path}'}
        cluster_HierarchicalClustering_query_count_result = pd.read_csv(cluster_file_path, index_col=0)
        
        st_names = cluster_HierarchicalClustering_query_count_result.index.tolist()
        valid_st_names = [name for name in st_names if name in expression_df.index]
        
        if not valid_st_names:
            return {'expression': {}, 'status': 'success'}
        
        filtered_df = expression_df.loc[valid_st_names]
        filtered_df = filtered_df.loc[:, (filtered_df != 0).any(axis=0)]
        
        top_genes = (filtered_df != 0).sum(axis=0).nlargest(50).index.tolist()
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
        expression_df = _load_gene_expression(expression_file_path)
        if expression_df is None:
            return {'status': 'fail', 'message': f'File not found: {expression_file_path}'}
        HierarchicalClustering_result_dir_path = os.path.join(base, 'HierarchicalClustering/')
        file_name = "cluster" + cluster.replace(" ", "_") + "_merged_data_with_labels.csv"
        cluster_file_path = os.path.join(HierarchicalClustering_result_dir_path, file_name)
        if not os.path.exists(cluster_file_path):
            return {'status': 'fail', 'message': f'File not found: {cluster_file_path}'}
        cluster_HierarchicalClustering_query_count_result = pd.read_csv(cluster_file_path, index_col=0)
        
        st_names = cluster_HierarchicalClustering_query_count_result.index.tolist()
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
