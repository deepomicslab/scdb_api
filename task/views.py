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


class taskViewSet(viewsets.ModelViewSet):
    queryset = tasks.objects.order_by('id')
    serializer_class = taskSerializer


@api_view(['GET'])
def viewtask(request):
    userid = request.query_params.dict()['userid']
    taskslist = tasks.objects.filter(user=userid)
    serializer = taskSerializer(taskslist, many=True)
    return Response({'results': serializer.data})

# @api_view(['GET'])
# def viewscquery(request):
#     userid = request.query_params.dict()['userid']
#     taskslist = tasks.objects.filter(user=userid)
#     serializer = taskSerializer(taskslist, many=True)
#     return Response({'results': serializer.data})
# name = models.CharField(max_length=300, blank=True, null=True)
# user = models.CharField(max_length=300, blank=True, null=True)
# userpath = models.CharField(max_length=200, blank=True, null=True)

# task_type = models.CharField(max_length=60, blank=True, null=True)
# modulelist = models.CharField(max_length=400, blank=True, null=True)
# status = models.CharField(max_length=60, blank=True, null=True)
# #stage = models.CharField(max_length=60, blank=True, null=True)
# task_detail = models.TextField(blank=True, null=True)
# created_at = models.DateTimeField(auto_now_add=True)

@api_view(['POST'])
def createtask(request):
    """
    Create a new task
    - submitfile
    - taskname
    - tasktype
    - userid
    - queryk
    """

    # create user task folder and save the file
    usertask_dir = str(int(time.time()))+'_' + \
            str(random.randint(1000, 9999))
    userpath = local_settings.USERTASKPATH+'/'+usertask_dir
    uploadfilepath = userpath + '/upload/'
    os.makedirs(uploadfilepath, exist_ok=False)
    file = request.FILES['submitfile']
    default_storage.save(uploadfilepath+'input.csv', ContentFile(file.read()))

    # save parameter in taskdetail.json
    taskdetailjson={'queryk': request.data['queryk']}
    with open(userpath+'/'+'taskdetail.json', 'w') as f:
        json.dump(taskdetailjson, f, ensure_ascii=False, indent=4)
    
    # create task object
    res = {}
    newtask = tasks.objects.create(
            name=request.data['taskname'], user=request.data['userid'], userpath=usertask_dir,
            task_type=request.data['tasktype'], status='Created')
    try:
        # run the task script
        with open(userpath+'/'+'taskdetail.json', 'r') as f:
            taskdetailjson = json.load(f)
        k=taskdetailjson['queryk']
        inputfile = userpath + '/upload/input.csv'
        outputdir = userpath + '/result/scquery'
        shell_script = local_settings.SCQUERY_SCRIPT
        script_arguments = [inputfile,str(k), outputdir]
        job_id = slurm_api.submit_job(shell_script, script_arguments=script_arguments)
        taskdetailjson['job_id'] = job_id
        with open(userpath+'/'+'taskdetail.json', 'w') as f:
            json.dump(taskdetailjson, f, ensure_ascii=False, indent=4)
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