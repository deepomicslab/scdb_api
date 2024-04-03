from utils import slurm_api
from scdb_api import settings_local as local_settings
import pandas as pd
from utils.page import paginate_dataframe
from utils.fileprocess import get_gene_list,get_cluster_list
#define a module class in analysis.py



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
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments,dependencies_job_ids=dependencies_jobs)
        self.status = 'Running'
        return self.job_id

class Scquery_old(Module):
    def __init__(self, name,path,params):
        super().__init__(name,path)
        inputfilepath=local_settings.USERTASKPATH +path+'/upload/query.csv'
        outputdir=local_settings.USERTASKPATH +path+'/result/scquery'
        paramk=str(params['k'])
        self.script_arguments = [inputfilepath,paramk,outputdir]
        #/home/platform/project/scdb_platform/scdb_api/workspace/module/sc_query_old
        self.shell_script = local_settings.SCDB_MODULE+'sc_query_old/run.sh'

class Scquery(Module):
    def __init__(self, name,path,params):
        super().__init__(name,path)
        inputfilepath=local_settings.USERTASKPATH +path+'/upload/input.h5ad'
        outputdir=local_settings.USERTASKPATH +path+'/result/'
        paramk=str(params['k'])
        projectname=params['projectname']
        self.script_arguments = [inputfilepath,outputdir,projectname,paramk]
        #/home/platform/project/scdb_platform/scdb_api/workspace/module/sc_query_old
        self.shell_script = local_settings.SCDB_MODULE+'sc_query/run.sh'
    def getmetaresult(self,page,pagesize):
        metadatafile=self.path+ f'/result/meta/{self.projectname}_meta_data.txt'
        metadata = pd.read_csv(metadatafile,sep='\t', index_col=False)
        count = metadata.shape[0]
        rename_dict = {'index': 'Cell_id',
                    'orig.ident':'orig_ident',
                    'Celltype..malignancy.': 'Celltype_malignancy',
                    'Celltype..major.lineage.':'Celltype_major_lineage'}
        metadata.rename(columns=rename_dict, inplace=True) # rename the first column
        metadata=paginate_dataframe(metadata, page, pagesize) # paginate the metadata
        res={'results': metadata.to_dict(orient='records'), 'count': count}
        return res
    def getumapresult(self):
        umapfile=self.path+ f'/result/umap/{self.projectname}_umap_data.txt'
        umappddata = pd.read_csv(umapfile, sep='\t', index_col=False)
        rename_dict = {'Unnamed: 0': 'Cell_id',}
        umappddata.rename(columns=rename_dict, inplace=True)
        res={'results': umappddata.to_dict(orient='records')}
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
    def getresult(self,query_params):
        resulttype = query_params.get('resulttype')
        if resulttype == 'metadata':
            return self.getmetaresult(int(query_params.gey('page')), int(query_params.gey('pagesize')))
        elif resulttype == 'umap':
            return self.getumapresult()
        elif resulttype == 'batcheffect':
            return self.getbatcheffect(query_params.get('compid'),query_params.get('gene'))
        elif resulttype == 'casuality':
            return self.getcasuality(query_params.get('cluster'))
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


# # 使用示例
# if __name__ == "__main__":
#     # 创建模块
#     module_a = Module('A')
#     module_b = Module('B')
#     module_c = Module('C')
#     module_d = Module('D')

#     # 添加依赖关系
#     module_b.add_dependency(module_a)
#     module_c.add_dependency(module_b)
#     module_d.add_dependency(module_b)
#     module_d.add_dependency(module_c)

#     # 创建管道并添加模块
#     pipeline = Pipeline()
#     pipeline.add_module(module_d)
#     pipeline.add_module(module_c)
#     pipeline.add_module(module_b)
#     pipeline.add_module(module_a)

#     # 执行管道
#     pipeline.execute()