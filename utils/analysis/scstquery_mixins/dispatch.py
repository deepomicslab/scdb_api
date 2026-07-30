import pandas as pd
from scdb_api import settings_local as local_settings


class DispatchMixin:
    """getresult/gettestresult dispatch methods for Scstquery."""

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
            return self.getLRSpearmanData(query_params.get('dataset'), query_params.get('mapping_method'))
        elif resulttype == 'lr_spearman':
            return self.getLRSpearmanData(query_params.get('dataset'), query_params.get('mapping_method'))
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
                type_col=query_params.get('type'),
                min_lr_score=query_params.get('min_lr_score'),
                max_lr_score=query_params.get('max_lr_score'),
                min_p_value=query_params.get('min_p_value'),
                max_p_value=query_params.get('max_p_value'),
                dataset=query_params.get('dataset'),
                mapping_method=query_params.get('mapping_method'),
            )
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
            return self.getLRSpearmanData(query_params.get('dataset'), query_params.get('mapping_method'))
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
                dataset=query_params.get('dataset'),
                mapping_method=query_params.get('mapping_method'),
            )
        elif resulttype == 'networkData':
            return self.getNetworkData(query_params.get('dataset'), query_params.get('type'))
        elif resulttype == 'img_path':
            return self.getImgpath(query_params.get('analysis_type'), query_params.get('img_id'))
        else:
            expressionfile=self.path+ '/result/scquery/sc_output_expression.csv'
            expression = pd.read_csv(expressionfile, index_col=0)
            return {'results': expression.to_dict(orient='records')}
