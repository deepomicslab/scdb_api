import os
import pandas as pd
from scdb_api import settings_local as local_settings

_RESULT_DISPATCH = {
    'metadata': ('getmetaresult', ['page', 'pagesize'], {}, True),
    'organsanddatasets': ('getOrgansAndDatasets', [], {}, False),
    'datasetInfo': ('getDatasetInfo', ['dataset'], {}, False),
    'filelist': ('getdownloadfilelist', ['flag'], {}, False),
    'scstmappingDownload': ('_scstmapping_resolve_file', ['dataset', 'method'], {}, False),
    'download': ('download', ['filename'], {}, False),
    'hescatter': ('getHEScatterresult', ['dataset'], {}, False),
    'he_distribution': ('getHEClusterDistribution', ['dataset'], {}, False),
    'countHeatmap': ('getQueryCountHeatmapResult', ['dataset'], {}, False),
    'hierarchicalClusteringStatus': ('getHierarchicalClusteringStatus', [], {}, False),
    'hierarchicalclusteringCelltypes': ('getHierarchicalClusteringQueryCelltypes', ['dataset'], {}, False),
    'hierarchicalclusteringCountHeatmap': ('getHierarchicalClusteringQueryCountHeatmapResult', ['dataset', 'cluster'], {}, False),
    'hierarchicalClusteringMarkerGenes': ('getHierarchicalClusteringMarkerGenes', ['dataset', 'cluster'], {}, False),
    'hierarchicalClusteringMarkerGeneExpressions': ('getHierarchicalClusteringMarkerGeneExpressions', ['dataset', 'cluster', 'gene'], {}, False),
    'LRPairs': ('getLRPairs', ['dataset', 'mapping_method', 'input_source'], {}, False),
    'LRreceivedSignalStrength': ('getReceivedSignalStrength', ['dataset', 'lr_pair', 'mapping_method', 'input_source'], {}, False),
    'networkData': ('getNetworkData', ['dataset', 'type', 'mapping_method', 'input_source'], {}, False),
    'cellchat_pathways': ('getCellChatPathways', ['dataset', 'mapping_method', 'input_source'], {}, False),
    'cellchat_circle': ('getCellChatCircleData', ['pathway', 'dataset', 'mapping_method', 'input_source'], {}, False),
    'cellchat_spatial': ('getCellChatSpatialData', ['pathway', 'dataset', 'mapping_method', 'input_source'], {}, False),
    'cellchat_heatmap': ('getCellChatHeatmapData', ['LR_pair', 'dataset', 'mapping_method', 'input_source'], {}, False),
    'cellchat_lrpairs': ('getCellChatLRPairs', ['dataset', 'mapping_method', 'input_source'], {}, False),
    'spider_init': ('getSpiderInit', ['dataset', 'mapping_method', 'input_source'], {}, False),
    'spider_coords': ('getSpiderCoords', ['dataset', 'mapping_method', 'input_source'], {}, False),
    'spider_pattern': ('getSpiderPatternData', ['dataset', 'pattern_id', 'mapping_method', 'input_source'], {}, False),
    'spider_lr': ('getSpiderLRData', ['dataset', 'lr_name', 'mapping_method', 'input_source'], {}, False),
    'lr_spearman': ('getLRSpearmanData', ['dataset', 'mapping_method'], {}, False),
    'scgpt_umap': ('getScgptUmap', ['dataset'], {}, False),
    'scgpt_heatmap': ('getScgptHeatmap', ['dataset'], {}, False),
    'scstmappingStatus': ('_scstmappingStatusFallback', ['dataset'], {}, False),
    'AlphaTalk': ('getAlphaTalkLRPairs', [], {
        'page': 1, 'pageSize': 15, 'sender': None, 'receiver': None,
        'ligand': None, 'sortBy': None, 'order': None, 'min_score': None,
        'max_score': None, 'get_metadata': None, 'receptor': None,
        'type': None, 'min_lr_score': None, 'max_lr_score': None,
        'min_p_value': None, 'max_p_value': None, 'dataset': None,
        'mapping_method': None, 'input_source': None,
    }, False),
}

_TEST_PARAM_OMISSIONS = {
    'cellchat_pathways': ['dataset'],
    'cellchat_circle': ['dataset'],
    'cellchat_spatial': ['dataset'],
    'cellchat_heatmap': ['dataset'],
    'cellchat_lrpairs': ['dataset'],
    'networkData': ['mapping_method'],
}

_TEST_UNSUPPORTED = {'datasetInfo'}


class DispatchMixin:
    """getresult/gettestresult dispatch methods for Scstquery."""

    def getresult(self, query_params):
        return self._dispatch(query_params, is_test=False)

    def gettestresult(self, query_params):
        self.path = local_settings.USERTASKPATH + 'demo_result/scst'
        self._is_demo = True
        return self._dispatch(query_params, is_test=True)

    def _dispatch(self, query_params, is_test):
        resulttype = query_params.get('resulttype')
        entry = _RESULT_DISPATCH.get(resulttype)

        if entry is None or (is_test and resulttype in _TEST_UNSUPPORTED):
            return self._fallback_csv()

        method_name, param_names, defaults, cast_int = entry
        method = getattr(self, method_name)

        if resulttype == 'AlphaTalk':
            kwargs = {}
            for p, default in defaults.items():
                val = query_params.get(p, default)
                key = 'type_col' if p == 'type' else p
                kwargs[key] = val
            return method(**kwargs)

        if is_test and resulttype in _TEST_PARAM_OMISSIONS:
            param_names = [p for p in param_names if p not in _TEST_PARAM_OMISSIONS[resulttype]]

        args = []
        for p in param_names:
            val = query_params.get(p)
            if cast_int and val is not None:
                val = int(val)
            args.append(val)
        return method(*args)

    def _fallback_csv(self):
        expressionfile = self.path + '/result/scquery/sc_output_expression.csv'
        if not os.path.exists(expressionfile):
            return {'status': 'fail', 'message': 'Unknown or unsupported resulttype'}
        expression = pd.read_csv(expressionfile, index_col=0)
        return {'results': expression.to_dict(orient='records')}