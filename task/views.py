from django.shortcuts import render
from task.models import tasks, SubTask
from dataset.models import Dataset
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
    print("receive request create task.")
    print("METHOD:", request.method)
    print("CONTENT_TYPE:", request.content_type)
    print("DATA:", request.data)
    print("FILES:", request.FILES)

    # create user task folder and save the file
    usertask_dir = str(int(time.time()))+'_' + str(random.randint(1000, 9999))
    userpath = local_settings.USERTASKPATH+usertask_dir
    uploadfilepath = userpath + '/upload/'
    os.makedirs(uploadfilepath, exist_ok=False)
    # file = request.FILES['submitfile']
    # default_storage.save(uploadfilepath+'input.h5ad', ContentFile(file.read()))
    # 确保 request.FILES 中有 'submitfile'
    if 'submitfile' in request.FILES:
        try:
            file = request.FILES['submitfile']
            
            with open(os.path.join(uploadfilepath, 'input.h5ad'), 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
            print("File saved successfully:", uploadfilepath + 'input.h5ad')
        except Exception as e:
            print("Upload error:", e)
            return Response({'status': 'Failed', 'message': f'File upload failed: {str(e)}'}, status=500)

        
    else:
        # 如果文件缺失，应返回错误
        return Response({'status': 'Failed', 'message': 'File "submitfile" not found in request.'}, status=400)
    # import shutil
    # shutil.copy("/home/platform/project/scdb_platform/scdb_api/workspace/user_data/1745249986_9226/upload/input.h5ad", uploadfilepath+'input.h5ad')

    # get parameters from request
    parameters_string=request.data['parameters']
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
    if 'testmode' in query_params and query_params['testmode'] == 'true':
        print("testmode")
        objectpath = local_settings.USERTASKPATH + 'demo_result/scst/moduleobject.pkl'
        with open(objectpath, 'rb') as f:
            #载入模块对象
            module = pickle.load(f)
        res = module.gettestresult(query_params)
        return Response(res)
    taskobject = tasks.objects.get(id=taskid)
    objectpath = local_settings.USERTASKPATH + taskobject.userpath + '/moduleobject.pkl'
    with open(objectpath, 'rb') as f:
        #载入模块对象
        module = pickle.load(f)
    res=module.getresult(query_params)
    return Response(res)


@api_view(['GET', 'HEAD'])
def getImg(request):
    image_analysis_type = request.query_params.get('image_analysis_type')
    image_id = request.query_params.get('image_id')
    # Optional resolution hint: 'thumbnail' returns a 500x500 max downscaled
    # PNG (cached separately as _tissue_thumbnail.png). Default returns the
    # full hires image (backwards compatible).
    resolution = request.query_params.get('resolution')

    if image_analysis_type == "he":
        from dataset.models import Dataset
        import h5py
        from PIL import Image

        # Try dataset_id (UUID) first, then fall back to title
        ds = None
        try:
            ds = Dataset.objects.get(dataset_id=image_id)
        except (Dataset.DoesNotExist, Dataset.MultipleObjectsReturned):
            try:
                ds = Dataset.objects.get(title=image_id)
            except Dataset.DoesNotExist:
                pass

        if not ds:
            return Response({'message': "No image for this dataset."}, status=404)

        # Pick cache path, max size, and content type based on resolution
        if resolution == 'thumbnail':
            # 缩略图用 JPEG（HE 连续色阶更适合 JPEG 压缩），400x400 max（卡片 250x170 显示够用）
            cache_path = ds.file_path.replace(".h5ad", "_tissue_thumbnail.jpg")
            max_size = 400
            content_type = 'image/jpeg'
            save_format = 'JPEG'
            save_kwargs = {'quality': 75, 'optimize': True}
        else:
            # 默认：PNG 完整分辨率（用于分析，不应压缩）
            cache_path = ds.file_path.replace(".h5ad", "_tissue_hires.png")
            max_size = None
            content_type = 'image/png'
            save_format = None
            save_kwargs = {}

        if not os.path.exists(cache_path):
            # Try to extract from h5ad
            try:
                with h5py.File(ds.file_path, "r") as f:
                    if "uns/spatial" not in f:
                        return Response({'message': "No image for this dataset."}, status=404)
                    for lib in f["uns/spatial"].keys():
                        for img_key in ("hires", "lowres"):
                            img_full = f"uns/spatial/{lib}/images/{img_key}"
                            if img_full in f:
                                img = Image.fromarray(f[img_full][:])
                                if max_size:
                                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                                if save_format:
                                    img.save(cache_path, save_format, **save_kwargs)
                                else:
                                    img.save(cache_path)
                                return FileResponse(open(cache_path, 'rb'), content_type=content_type)
            except Exception as e:
                print(f"[getImg] error extracting image for {image_id}: {e}")
            return Response({'message': "No image for this dataset."}, status=404)

        return FileResponse(open(cache_path, 'rb'), content_type=content_type)
    else:
        return Response({'message': f"No such analysis_type {image_analysis_type}"}, status=400)
    
@api_view(['POST'])
def create_subtask(request):
    """
    创建 scst 子任务（硬编码 SubScstquery 模块，自理目录/文件）
    - taskid (主任务 ID)
    - userid
    - dataset_path (数据集 ID)
    - subtasktype (子任务类型，如 "xx1")
    - parameters (JSON 字符串，e.g., {"k": 10, "sub_type": "hierarchical"})
    """
    res = {}
    taskid = request.data.get('taskid')
    userid = request.data.get('userid')
    dataset_path = request.data.get('dataset_path')  # 新增：数据集 ID
    subtasktype = request.data.get('subtasktype')
    print(taskid, userid, dataset_path, subtasktype)
    if not taskid or not userid or not dataset_path or not subtasktype:
        res['status'] = 'Failed'
        res['message'] = '缺少 taskid、userid、dataset_path 或 subtasktype'
        return Response(res, status=400)

    try:
        main_task = tasks.objects.get(id=taskid, user=userid)
        # if main_task.status != 'Completed':
        #     return Response({'status': 'Failed', 'message': '主任务未完成'}, status=400)
    except tasks.DoesNotExist:
        res['status'] = 'Failed'
        res['message'] = '任务不存在'
        return Response(res, status=404)

    # 解析参数，并加路径信息（供模块用）
    parameters_string = request.data.get('parameters')
    if not parameters_string:
        res['status'] = 'Failed'
        res['message'] = '缺少 parameters'
        return Response(res, status=400)
    parameters_dict = json.loads(parameters_string)
    usertask_dir = main_task.userpath
    parameters_dict['userid'] = userid
    if 'projectname' not in parameters_dict:
        parameters_dict['projectname'] = 'test'

    # 创建子任务记录
    new_subtask = SubTask.objects.create(
        main_task=main_task,
        subtask_type=subtasktype,
        dataset_path=dataset_path,
        status='Created',
        parameters=parameters_dict
    )

    # 硬编码加载 SubScstquery 模块
    try:
        def get_class_from_module(module, class_name):
            return getattr(module, class_name, None)

        cls = get_class_from_module(utils.analysis, 'SubScstquery')  # 硬编码类名
        if cls is None:
            raise ValueError('SubScstquery 模块未找到')

        # 模块自理目录/文件：传子任务名 + params (含路径)
        # Resolve dataset UUID from Dataset model
        dataset_id = request.data.get('dataset_id', '')
        dataset_uuid = ''
        st_h5ad_path = ''
        if dataset_id:
            try:
                ds = Dataset.objects.get(dataset_id=dataset_id)
                # Extract UUID from file_path: /data3/.../uuid/st_filtered_adata/...
                dataset_uuid = os.path.splitext(os.path.basename(ds.file_path))[0]
                st_h5ad_path = ds.file_path
            except Dataset.DoesNotExist:
                pass
        new_submodule = cls(subtasktype, usertask_dir, dataset_uuid, dataset_path, st_h5ad_path, parameters_dict)  # __init__(name, uuid, marker_path, params)

        # Auto-chain hierarchical_clustering as prerequisite for tools that depend on it
        needs_hierarchical_clustering = subtasktype in ('recall_analysis', 'commot')
        if needs_hierarchical_clustering:
            hc_result_dir = os.path.join(local_settings.USERTASKPATH, usertask_dir, f'dataset_{dataset_uuid}', 'subtask_hierarchical_clustering', 'result', 'he', 'HierarchicalClustering')
            if not (os.path.isdir(hc_result_dir) and os.listdir(hc_result_dir)):
                hc_params = parameters_dict.copy()
                hc_params['sub_type'] = 'hierarchical_clustering'
                if 'organParts' not in hc_params:
                    hc_params['organParts'] = ''
                if 'projectname' not in hc_params:
                    hc_params['projectname'] = 'test'
                hc_module = cls('hierarchical_clustering', usertask_dir, dataset_uuid, dataset_path, st_h5ad_path, hc_params)
                hc_job_id = hc_module.process()
                if hc_job_id and hc_job_id != 'skipped_existing':
                    new_submodule.add_dependency(hc_module)
                    # Create HC SubTask record and store in viewer params for tracking
                    hc_subtask = SubTask.objects.create(
                        main_task=main_task,
                        subtask_type='hierarchical_clustering',
                        dataset_path=dataset_path,
                        status='Running',
                        job_id=hc_job_id,
                        parameters=hc_params
                    )
                    parameters_dict['_hc_subtask_id'] = hc_subtask.id
                    parameters_dict['_hc_job_id'] = hc_job_id
                    print(f'Auto-created HC subtask id={hc_subtask.id}, job_id={hc_job_id}')

        # Auto-chain he_scatter as prerequisite for annotation_mapping
        needs_he_scatter = subtasktype == 'annotation_mapping'
        if needs_he_scatter:
            he_scatter_result = os.path.join(local_settings.USERTASKPATH, usertask_dir, f'dataset_{dataset_uuid}', 'subtask_he_scatter', 'result', 'he', 'all_merged_data_with_labels.csv')
            if not os.path.isfile(he_scatter_result):
                hs_params = parameters_dict.copy()
                hs_params['sub_type'] = 'he_scatter'
                if 'organParts' not in hs_params:
                    hs_params['organParts'] = ''
                if 'projectname' not in hs_params:
                    hs_params['projectname'] = 'test'
                hs_module = cls('he_scatter', usertask_dir, dataset_uuid, dataset_path, st_h5ad_path, hs_params)
                hs_job_id = hs_module.process()
                if hs_job_id and hs_job_id != 'skipped_existing':
                    new_submodule.add_dependency(hs_module)
                    hs_subtask = SubTask.objects.create(
                        main_task=main_task,
                        subtask_type='he_scatter',
                        dataset_path=dataset_path,
                        status='Running',
                        job_id=hs_job_id,
                        parameters=hs_params
                    )
                    parameters_dict['_hs_subtask_id'] = hs_subtask.id
                    parameters_dict['_hs_job_id'] = hs_job_id
                    print(f'Auto-created HE scatter subtask id={hs_subtask.id}, job_id={hs_job_id}')

        job_id = new_submodule.process()
        print(job_id)

        # 保存状态/文件（用 module 自身的 status，支持 viewer/pending 等非 Running 状态）
        new_subtask.job_id = job_id
        new_subtask.status = new_submodule.status if new_submodule.status else 'Running'
        new_subtask.parameters = parameters_dict
        new_subtask.save()

        # taskdetailjson = [{'subtasktype': subtasktype, 'parameters_dict': parameters_dict, 'job_id': job_id, 'status': 'Created'}]
        # with open(new_submodule.path + '/taskdetail.json', 'w') as f:
        #     json.dump(taskdetailjson, f, ensure_ascii=False, indent=4)
        # with open(new_submodule.path + '/moduleobject.pkl', 'wb') as f:
        #     pickle.dump(new_submodule, f)

        res['status'] = 'Success'
        res['message'] = '子任务创建成功'
        res['data'] = {'subtaskid': new_subtask.id, 'sub_dir': new_submodule.path}
    except Exception as e:
        res['status'] = 'Failed'
        res['message'] = f'子任务创建失败：{str(e)}'
        new_subtask.status = 'Failed'
        new_subtask.save()
        traceback.print_exc()

    return Response(res)

# view.py
@api_view(['GET'])
def subtask_status_update(request):
    # for subtask in SubTask.objects.all().order_by('-id'):
    #     print(f"ID: {subtask.id}, Main ID: {subtask.main_task.id}, Type: {subtask.subtask_type}, Status: {subtask.status}")
    # return
    """
    按需获取并更新子任务的实时状态 (不依赖 PKL 文件)。
    参数: subtaskid
    """
    subtaskid = request.query_params.get('subtaskid')
    NON_FINAL_STATES = ["RUNNING", "PENDING", "CONFIGURING", "COMPLETING", "REQUEUED", "SUSPENDED"]
    res = {'status': 'Failed', 'message': 'Invalid request.'}

    if not subtaskid:
        res['message'] = '缺少 subtaskid 参数。'
        return Response(res, status=400)

    try:
        subtask = SubTask.objects.get(id=subtaskid)
        current_db_status = subtask.status
        job_id = subtask.job_id

    except SubTask.DoesNotExist:
        res['message'] = f'ID 为 {subtaskid} 的子任务不存在。'
        return Response(res, status=404)

    # 1. 如果数据库状态已经是终态，直接返回
    if current_db_status.upper() not in NON_FINAL_STATES:
        return Response({
            'status': 'Success',
            'current_status': current_db_status,
            'job_id': job_id
        })
        
    # 2. 非 Slurm 作业类型（viewer/跳过），直接返回数据库状态
    if job_id in ('viewer_only', 'skipped_existing'):
        return Response({
            'status': 'Success',
            'current_status': current_db_status,
            'job_id': job_id,
            'message': 'Non-slurm task.'
        })

    # 2b. Pending viewer waiting for HC subtask to complete
    if job_id == 'pending_hc' and subtask.subtask_type == 'recall_analysis':
        hc_subtask = SubTask.objects.filter(
            main_task=subtask.main_task,
            subtask_type='hierarchical_clustering',
            dataset_path=subtask.dataset_path
        ).order_by('-id').first()
        if hc_subtask:
            # Update HC status from Slurm if needed
            if hc_subtask.status.upper() in NON_FINAL_STATES and hc_subtask.job_id and hc_subtask.job_id not in ('viewer_only', 'skipped_existing', 'pending_hc'):
                try:
                    slurm_status = slurm_api.get_job_status(hc_subtask.job_id)
                    if slurm_status:
                        slurm_status = slurm_status.rstrip('+').upper()
                        if slurm_status != hc_subtask.status:
                            hc_subtask.status = slurm_status
                            hc_subtask.save()
                except Exception:
                    pass
        if hc_subtask and hc_subtask.status in ('Completed', 'COMPLETED'):
            subtask.status = 'Completed'
            subtask.job_id = 'viewer_only'
            subtask.save()
            return Response({
                'status': 'Success',
                'current_status': 'Completed',
                'job_id': 'viewer_only',
                'message': 'HC completed, viewer ready.'
            })
        hc_job = subtask.parameters.get('_hc_job_id', 'unknown')
        return Response({
            'status': 'Success',
            'current_status': 'Pending',
            'job_id': job_id,
            'hc_job_id': hc_job,
            'message': f'Waiting for HC subtask (job {hc_job}) to complete.'
        })

    # 2c. Pending viewer waiting for he_scatter subtask to complete
    if job_id == 'pending_he_scatter' and subtask.subtask_type == 'annotation_mapping':
        hs_subtask = SubTask.objects.filter(
            main_task=subtask.main_task,
            subtask_type='he_scatter',
            dataset_path=subtask.dataset_path
        ).order_by('-id').first()
        if hs_subtask:
            if hs_subtask.status.upper() in NON_FINAL_STATES and hs_subtask.job_id and hs_subtask.job_id not in ('viewer_only', 'skipped_existing', 'pending_he_scatter'):
                try:
                    slurm_status = slurm_api.get_job_status(hs_subtask.job_id)
                    if slurm_status:
                        slurm_status = slurm_status.rstrip('+').upper()
                        if slurm_status != hs_subtask.status:
                            hs_subtask.status = slurm_status
                            hs_subtask.save()
                except Exception:
                    pass
        if hs_subtask and hs_subtask.status in ('Completed', 'COMPLETED'):
            subtask.status = 'Completed'
            subtask.job_id = 'viewer_only'
            subtask.save()
            return Response({
                'status': 'Success',
                'current_status': 'Completed',
                'job_id': 'viewer_only',
                'message': 'HE scatter completed, annotation viewer ready.'
            })
        hs_job = subtask.parameters.get('_hs_job_id', 'unknown')
        return Response({
            'status': 'Success',
            'current_status': 'Pending',
            'job_id': job_id,
            'hs_job_id': hs_job,
            'message': f'Waiting for HE scatter subtask (job {hs_job}) to complete.'
        })

    # 3. 如果 job_id 为空，但状态不是终态，可能是提交失败
    if not job_id:
        # 如果是这种情况，需要根据您业务定义是返回 Failed 还是 Pending
        return Response({'status': 'Success', 'current_status': current_db_status, 'message': '任务 Job ID 丢失。'})

    # 4. 状态需要更新 (非终态且有 job_id)
    try:
        # 直接调用 SLURM API 查询实时状态
        new_slurm_status = slurm_api.get_job_status(job_id)
        if new_slurm_status:
            new_slurm_status = new_slurm_status.rstrip("+")
        
        # 如果 SLURM API 返回 None 或空字符串，说明任务可能还在处理中，保持当前数据库状态
        if not new_slurm_status:
             return Response({
                'status': 'Success',
                'current_status': current_db_status,
                'job_id': job_id,
                'message': 'SLURM 状态暂时无法查询，维持当前状态。'
            })
             
        # SLURM 状态通常是大写，保持一致性
        new_slurm_status = new_slurm_status.upper() 

        # 4. 更新数据库
        if new_slurm_status != current_db_status:
            subtask.status = new_slurm_status
            subtask.save()
        
        return Response({
            'status': 'Success',
            'current_status': new_slurm_status,
            'job_id': job_id,
            'message': f'状态已更新至 {new_slurm_status}'
        })

    except Exception as e:
        traceback.print_exc()
        res['message'] = f'SLURM 状态查询失败: {str(e)}'
        return Response(res, status=500)