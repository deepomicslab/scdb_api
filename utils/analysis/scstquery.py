from scdb_api import settings_local as local_settings
from .base import Module
from .scstquery_mixins import (
    CommonMixin,
    HEScatterMixin,
    HierarchicalClusteringMixin,
    CommotMixin,
    CellChatMixin,
    SpiderMixin,
    AlphaTalkMixin,
    ScgptMixin,
    DispatchMixin,
)


class Scstquery(Module, CommonMixin, HEScatterMixin, HierarchicalClusteringMixin,
                CommotMixin, CellChatMixin, SpiderMixin, AlphaTalkMixin,
                ScgptMixin, DispatchMixin):
    def __init__(self, name, path, params):
        super().__init__(name, path)
        inputfilepath = local_settings.USERTASKPATH + path + '/upload/input.h5ad'
        outputdir = local_settings.USERTASKPATH + path + '/result/'
        paramk = str(params['k'])
        projectname = params['projectname']
        organs = params['organParts']
        disease = params['disease']
        if params['processType'] == "cluster":
            self.script_arguments = [inputfilepath, outputdir, projectname, '190', '1.2', 'cluster', organs]
        elif params['processType'] == "celltype":
            self.script_arguments = [inputfilepath, outputdir, projectname, '190', '1.2', 'cell_type', organs, disease]
        self.shell_script = local_settings.SCDB_MODULE + 'scst_query/run.sh'
