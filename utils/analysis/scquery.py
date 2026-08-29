import os
import pandas as pd
from scdb_api import settings_local as local_settings
from utils.page import paginate_dataframe
from utils.fileprocess import get_gene_list, get_cluster_list
from utils.analysis.scstquery_mixins.common import read_task_file_b64
from .base import Module


class Scquery(Module):
    def __init__(self, name,path,params):
        super().__init__(name,path)
        inputfilepath=local_settings.USERTASKPATH +path+'/upload/input.h5ad'
        outputdir=local_settings.USERTASKPATH +path+'/result/'
        projectname=params['projectname']
        self.script_arguments = [inputfilepath,outputdir,projectname,'50','0.8']
        # module/sc_query/ is the legacy single-cell pipeline (see sc_query_old note
        # in settings_local — SCQUERY_SCRIPT is unused; this is the live script)
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
        default_value = 'default'  # can be a number, string, etc.
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
        # Legacy contract is bare filenames only (see getdownloadfilelist), so any
        # name with a separator is rejected outright. Everything else - absolute
        # paths, ".." traversal, symlink escapes, server-internal metadata - is
        # guarded by the shared validator also used by CommonMixin.download.
        if filename and '/' in filename:
            return {'status': 'fail', 'message': 'Invalid filename.'}
        return read_task_file_b64(self.path, filename)
    
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
        elif resulttype == 'scstmappingStatus':
            return self._scstmappingStatusFallback(query_params.get('dataset'))
        else:
            expressionfile=self.path+ '/result/scquery/sc_output_expression.csv'
            expression = pd.read_csv(expressionfile, index_col=0)
            return {'results': expression.to_dict(orient='records')}
