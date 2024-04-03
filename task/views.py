from django.shortcuts import render
from task.models import tasks
from task.serializers import taskSerializer
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import viewsets
import os,traceback
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
# Create your views here.
import time,random,json
from scdb_api import settings_local as local_settings
from utils import slurm_api
from django.http import FileResponse
import pandas as pd
import utils.analysis 
from utils.page import paginate_dataframe
from utils.fileprocess import get_gene_list,get_cluster_list
import pickle

class taskViewSet(viewsets.ModelViewSet):
    queryset = tasks.objects.order_by('id')
    serializer_class = taskSerializer


@api_view(['GET'])
def viewtask(request):
    userid = request.query_params.dict()['userid']
    taskslist = tasks.objects.filter(user=userid)
    serializer = taskSerializer(taskslist, many=True)
    return Response({'results': serializer.data})


@api_view(['POST'])
def createtask(request):
    """
    Create a new task
    - userid
    - submitfile
    - taskname
    - tasktype
    - projectname
    - modulename
    - parameters
    """
    # create user task folder and save the file
    usertask_dir = str(int(time.time()))+'_' + str(random.randint(1000, 9999))
    userpath = local_settings.USERTASKPATH+usertask_dir
    uploadfilepath = userpath + '/upload/'
    os.makedirs(uploadfilepath, exist_ok=False)
    file = request.FILES['submitfile']
    default_storage.save(uploadfilepath+'input.h5ad', ContentFile(file.read()))

    # get parameters from request
    parameters_string=request.data['parameters']
    print(parameters_string)
    parameters_dict = json.loads(parameters_string)

    # create task object
    res = {}
    newtask = tasks.objects.create(
            name=request.data['taskname'], user=request.data['userid'], userpath=usertask_dir,
            task_type=request.data['tasktype'], status='Created',modulelist=request.data['modulename'])
    
    # create module object and run the task
    if newtask.task_type == 'module':
        try:
            # run the task script
            def get_class_from_module(module, class_name):
                # 使用 getattr() 尝试从模块中获取类对象,如果类不存在，则返回 None
                return getattr(module, class_name, None)
            cls = get_class_from_module(utils.analysis,request.data['modulename'])
            
            if cls is None:
                res['status'] = 'Failed'
                newtask.status = 'Failed'
                res['message'] = 'module not found'
                raise ValueError('module not found')

            else:
                newmodule = cls(request.data['taskname'],usertask_dir,parameters_dict)
                job_id = newmodule.process()

                taskdetailjson=[{'modulename':request.data['modulename'],'parameters_dict': parameters_dict, 'job_id': job_id, 'status': 'Created'}]
                with open(userpath+'/'+'taskdetail.json', 'w') as f:
                    json.dump(taskdetailjson, f, ensure_ascii=False, indent=4)
                with open(userpath+'/moduleobject.pkl', 'wb') as f:
                    pickle.dump(newmodule, f)
                newtask.status = 'Running'
                res['status'] = 'Success'
                res['message'] = 'task create successfully'
                res['data'] = {'taskid': newtask.id}
        except Exception as e:
            res['status'] = 'Failed'
            res['message'] = e
            newtask.status = 'Failed'
            traceback.print_exc()
    newtask.save()
    return Response(res)


@api_view(['GET'])
def viewtasklist(request):
    userid = request.query_params.dict()['userid']
    taskslist = tasks.objects.filter(user=userid)
    serializer = taskSerializer(taskslist, many=True)
    return Response({'results': serializer.data})

@api_view(['GET'])
def taskdetailview(request):
    taskid = request.query_params.dict()['taskid']
    taskobject = tasks.objects.filter(id=taskid)
    serializer = taskSerializer(taskobject, many=True)
    taskdata=serializer.data[0]
    taskdata['inputpath'] =   local_settings.FILEAPI+taskdata['userpath']+ '/upload/input.csv'
    taskdata['outputpath'] =  {'metadata':local_settings.FILEAPI+taskdata['userpath']+ '/result/scquery/sc_output_meta.csv',\
                            'expression':local_settings.FILEAPI+taskdata['userpath']+ '/result/scquery/sc_output_expression.csv'}
    return Response({'results': taskdata})

@api_view(['GET'])
def getoutputfile(request, path):
    file_path = local_settings.USERTASKPATH  + path
    file = open(file_path, 'rb')
    response = FileResponse(file)
    filename = file.name.split('/')[-1]
    response['Content-Disposition'] = "attachment; filename="+filename
    response['Content-Type'] = 'text/plain'
    return response


@api_view(['GET'])
def taskresultview(request):
    """
    Get task result: metadata, expression, umap, casuality
    - taskid*
    - resulttype*: metadata/expression/umap/batcheffect/casuality
    - metadata: page, pagesize (optional)
    - batcheffect: gene, compid (optional)
    - casuality: cluster (optional)
    """
    query_params = request.query_params.dict()
    taskid = query_params['taskid']
    taskobject = tasks.objects.get(id=taskid)
    objectpath = local_settings.USERTASKPATH + taskobject.userpath + '/moduleobject.pkl'
    with open(objectpath, 'rb') as f:
        #载入模块对象
        module = pickle.load(f)
    res=module.getresult(query_params)
    return Response(res)

