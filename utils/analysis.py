from utils import slurm_api
from scdb_api import settings_local as local_settings

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
        return slurm_api.get_job_status(self.job_id)

    def process(self):

        if self.shell_script is None:
            raise ValueError("Shell script is not set. Cannot process module.")
        if len(self.dependencies) == 0:
            print(self.shell_script,self.script_arguments)
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments)
        else:
            dependencies_jobs = [dependency.job_id for dependency in self.dependencies if dependency.job_id is not None]
            self.job_id = slurm_api.submit_job(self.shell_script,script_arguments=self.script_arguments,dependencies_job_ids=dependencies_jobs)
        self.status = 'Running'
        return self.job_id

class Scquery(Module):
    def __init__(self, name,path,params):
        super().__init__(name,path)
        inputfilepath=local_settings.USERTASKPATH +path+'/upload/query.csv'
        outputdir=local_settings.USERTASKPATH +path+'/result/scquery'
        paramk=str(params['k'])
        self.script_arguments = [inputfilepath,paramk,outputdir]
        #/home/platform/project/scdb_platform/scdb_api/workspace/module/sc_query_old
        self.shell_script = local_settings.SCDB_MODULE+'sc_query_old/run.sh'

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