from django.shortcuts import render
from task.models import tasks, SubTask, TaskStatus, SLURM_ACTIVE_STATES, PSEUDO_JOB_IDS
from dataset.models import Dataset
from task.serializers import taskSerializer
from task.services import get_module_class, create_subtask as create_subtask_service
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import viewsets
import os,traceback
import time,random,json
from scdb_api import settings_local as local_settings
from utils import slurm_api
from utils.slurm_api import normalize_slurm_status
from django.http import FileResponse
import pandas as pd
import utils.analysis 
from utils.page import paginate_dataframe
from utils.fileprocess import get_gene_list,get_cluster_list
from utils.mapping_paths import check_mapping_completed
import pickle


def _sync_dependency_from_slurm(dep_subtask):
    """Check SLURM status for a dependency subtask and update its DB status.
    Used for auto-chained HC/HE prerequisites that aren't directly polled by frontend.
    """
    if not dep_subtask:
        return
    status_upper = (dep_subtask.status or '').upper()
    if status_upper not in SLURM_ACTIVE_STATES:
        return
    if not dep_subtask.job_id or dep_subtask.job_id in PSEUDO_JOB_IDS:
        return
    try:
        new_status = dep_subtask.sync_from_slurm()
        if new_status and new_status != dep_subtask.status:
            dep_subtask.save()
    except Exception:
        pass

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
    try:
        parameters_dict = json.loads(parameters_string)
    except (json.JSONDecodeError, TypeError) as e:
        return Response({'status': 'Failed', 'message': f'Invalid parameters JSON: {str(e)}'}, status=400)

    # create task object
    res = {}
    newtask = tasks.objects.create(
            name=request.data['taskname'], user=request.data['userid'], userpath=usertask_dir,
            task_type=request.data['tasktype'], status=TaskStatus.CREATED, modulelist=request.data['modulename'])
    
    # create module object and run the task
    if newtask.task_type == 'module':
        try:
            cls = get_module_class(request.data['modulename'])
            
            if cls is None:
                res['status'] = 'Failed'
                newtask.status = TaskStatus.FAILED
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
                newtask.status = TaskStatus.RUNNING
                res['status'] = 'Success'
                res['message'] = 'task create successfully'
                res['data'] = {'taskid': newtask.id}
        except Exception as e:
            res['status'] = 'Failed'
            res['message'] = str(e)
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
    taskid = request.query_params.dict().get('taskid', '')
    if not taskid:
        return Response({'status': 'error', 'message': 'Missing taskid'}, status=400)
    taskobject = tasks.objects.filter(id=taskid)
    if not taskobject.exists():
        return Response({'status': 'error', 'message': 'Task not found'}, status=404)
    serializer = taskSerializer(taskobject, many=True)
    taskdata=serializer.data[0]
    taskdata['inputpath'] =   local_settings.FILEAPI+taskdata['userpath']+ '/upload/input.csv'
    taskdata['outputpath'] =  {'metadata':local_settings.FILEAPI+taskdata['userpath']+ '/result/scquery/sc_output_meta.csv',\
                            'expression':local_settings.FILEAPI+taskdata['userpath']+ '/result/scquery/sc_output_expression.csv'}
    return Response({'results': taskdata})

@api_view(['GET'])
def getoutputfile(request, path):
    base_dir = os.path.realpath(local_settings.USERTASKPATH)
    file_path = os.path.realpath(os.path.join(base_dir, path))
    if not file_path.startswith(base_dir + os.sep) and file_path != base_dir:
        return Response({'status': 'error', 'message': 'Access denied'}, status=403)
    if not os.path.isfile(file_path):
        return Response({'status': 'error', 'message': 'File not found'}, status=404)
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
    taskid = query_params.get('taskid', '')
    if not taskid:
        return Response({'status': 'error', 'message': 'Missing taskid'}, status=400)
    if 'testmode' in query_params and query_params['testmode'] == 'true':
        print("testmode")
        objectpath = local_settings.USERTASKPATH + 'demo_result/scst/moduleobject.pkl'
        with open(objectpath, 'rb') as f:
            #载入模块对象
            module = pickle.load(f)
        res = module.gettestresult(query_params)
        return Response(res)
    try:
        taskobject = tasks.objects.get(id=taskid)
    except tasks.DoesNotExist:
        return Response({'status': 'error', 'message': 'Task not found'}, status=404)
    objectpath = local_settings.USERTASKPATH + taskobject.userpath + '/moduleobject.pkl'
    with open(objectpath, 'rb') as f:
        #载入模块对象
        module = pickle.load(f)
    res=module.getresult(query_params)
    # scstmappingDownload returns a {'_stream_file': path, 'filename': ...} marker ->
    # stream the h5ad as a FileResponse instead of base64-encoding it into a JSON body
    # (avoids loading multi-MB files into memory + client-side atob churn).
    if isinstance(res, dict) and res.get('_stream_file'):
        return FileResponse(open(res['_stream_file'], 'rb'),
                            as_attachment=True,
                            filename=res.get('filename', 'mapping.h5ad'),
                            content_type='application/octet-stream')
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

        # 3 档 resolution：
        #   thumbnail : 400x400 JPEG q75  (~13KB)  — 卡片缩略图
        #   medium    : 800x800 JPEG q80  (~50-100KB) — 散点图底图（默认）
        #   original  : 完整分辨率 JPEG q85 (~1MB)   — 高清 opt-in
        if resolution == 'thumbnail':
            cache_path = ds.file_path.replace(".h5ad", "_tissue_thumbnail.jpg")
            max_size = 400
            content_type = 'image/jpeg'
            save_format = 'JPEG'
            save_kwargs = {'quality': 75, 'optimize': True}
        elif resolution == 'original':
            cache_path = ds.file_path.replace(".h5ad", "_tissue_hires.jpg")
            max_size = None  # 完整分辨率
            content_type = 'image/jpeg'
            save_format = 'JPEG'
            save_kwargs = {'quality': 85, 'optimize': True}
        else:
            # 默认（无 param 或 ?resolution=medium）：medium
            cache_path = ds.file_path.replace(".h5ad", "_tissue_medium.jpg")
            max_size = 800
            content_type = 'image/jpeg'
            save_format = 'JPEG'
            save_kwargs = {'quality': 80, 'optimize': True}

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
    创建 scst 子任务
    - taskid (主任务 ID)
    - userid
    - dataset_path (数据集 ID)
    - subtasktype (子任务类型)
    - parameters (JSON 字符串)
    """
    taskid = request.data.get('taskid')
    userid = request.data.get('userid')
    dataset_path = request.data.get('dataset_path')
    dataset_id = request.data.get('dataset_id', '')
    subtasktype = request.data.get('subtasktype')

    if not taskid or not userid or not dataset_path or not subtasktype:
        return Response({'status': 'Failed', 'message': '缺少 taskid、userid、dataset_path 或 subtasktype'}, status=400)

    try:
        main_task = tasks.objects.get(id=taskid, user=userid)
    except tasks.DoesNotExist:
        return Response({'status': 'Failed', 'message': '任务不存在'}, status=404)

    parameters_string = request.data.get('parameters')
    if not parameters_string:
        return Response({'status': 'Failed', 'message': '缺少 parameters'}, status=400)
    try:
        parameters_dict = json.loads(parameters_string)
    except (json.JSONDecodeError, TypeError) as e:
        return Response({'status': 'Failed', 'message': f'Invalid parameters JSON: {str(e)}'}, status=400)

    try:
        result = create_subtask_service(main_task, userid, dataset_path, dataset_id, subtasktype, parameters_dict)
        return Response(result)
    except ValueError as e:
        traceback.print_exc()
        return Response({'status': 'Failed', 'message': str(e)}, status=400)
    except Exception as e:
        traceback.print_exc()
        return Response({'status': 'Failed', 'message': f'子任务创建失败：{str(e)}'})

# view.py
@api_view(['GET'])
def subtask_status_update(request):
    """
    按需获取并更新子任务的实时状态 (不依赖 PKL 文件)。
    参数: subtaskid
    """
    subtaskid = request.query_params.get('subtaskid')

    if not subtaskid:
        return Response({'status': 'Failed', 'message': '缺少 subtaskid 参数。'}, status=400)

    try:
        subtask = SubTask.objects.get(id=subtaskid)
    except SubTask.DoesNotExist:
        return Response({'status': 'Failed', 'message': f'ID 为 {subtaskid} 的子任务不存在。'}, status=404)

    current_db_status = subtask.status or ''
    job_id = subtask.job_id
    status_upper = current_db_status.upper()

    # 0. Sync auto-chained HC dependency for commot/cellchat/spider
    if subtask.subtask_type in ('commot', 'cellchat', 'spider'):
        hc_subtask_id = (subtask.parameters or {}).get('_hc_subtask_id')
        if hc_subtask_id:
            try:
                hc = SubTask.objects.get(id=hc_subtask_id)
                _sync_dependency_from_slurm(hc)
            except SubTask.DoesNotExist:
                pass

    # 1. Terminal state - return immediately
    if status_upper not in SLURM_ACTIVE_STATES:
        return Response({
            'status': 'Success',
            'current_status': current_db_status,
            'job_id': job_id
        })

    # 2. Non-slurm pseudo job_ids (viewer/skipped)
    if job_id in PSEUDO_JOB_IDS and job_id in ('viewer_only', 'skipped_existing'):
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
        _sync_dependency_from_slurm(hc_subtask)
        if hc_subtask and (hc_subtask.status or '').upper() == 'COMPLETED':
            subtask.status = TaskStatus.COMPLETED
            subtask.job_id = 'viewer_only'
            subtask.save()
            return Response({
                'status': 'Success',
                'current_status': TaskStatus.COMPLETED,
                'job_id': 'viewer_only',
                'message': 'HC completed, viewer ready.'
            })
        hc_job = (subtask.parameters or {}).get('_hc_job_id', 'unknown')
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
        _sync_dependency_from_slurm(hs_subtask)
        if hs_subtask and (hs_subtask.status or '').upper() == 'COMPLETED':
            subtask.status = TaskStatus.COMPLETED
            subtask.job_id = 'viewer_only'
            subtask.save()
            return Response({
                'status': 'Success',
                'current_status': TaskStatus.COMPLETED,
                'job_id': 'viewer_only',
                'message': 'HE scatter completed, annotation viewer ready.'
            })
        hs_job = (subtask.parameters or {}).get('_hs_job_id', 'unknown')
        return Response({
            'status': 'Success',
            'current_status': 'Pending',
            'job_id': job_id,
            'hs_job_id': hs_job,
            'message': f'Waiting for HE scatter subtask (job {hs_job}) to complete.'
        })

    # 3. job_id is empty but status is non-terminal
    if not job_id:
        return Response({
            'status': 'Success',
            'current_status': current_db_status,
            'message': '任务 Job ID 丢失。'
        })

    # 4. Query SLURM and update
    try:
        raw_status = slurm_api.get_job_status(job_id)
        if not raw_status:
            return Response({
                'status': 'Success',
                'current_status': current_db_status,
                'job_id': job_id,
                'message': 'SLURM 状态暂时无法查询，维持当前状态。'
            })

        new_status = normalize_slurm_status(raw_status)

        if new_status != current_db_status:
            subtask.status = new_status
            subtask.save()

        return Response({
            'status': 'Success',
            'current_status': new_status,
            'job_id': job_id,
            'message': f'状态已更新至 {new_status}'
        })

    except Exception as e:
        traceback.print_exc()
        return Response({'status': 'Failed', 'message': f'SLURM 状态查询失败: {str(e)}'}, status=500)
@api_view(['GET'])
def subtask_log(request):
    """Return the last 500 lines of a subtask's SLURM log file."""
    subtaskid = request.query_params.get('subtaskid')
    if not subtaskid:
        return Response({'status': 'Failed', 'message': 'Missing subtaskid parameter.'}, status=400)
    try:
        subtask = SubTask.objects.get(id=subtaskid)
    except SubTask.DoesNotExist:
        return Response({'status': 'Failed', 'message': f'SubTask {subtaskid} not found.'}, status=404)

    job_id = subtask.job_id
    subtask_type = subtask.subtask_type
    params = subtask.parameters if isinstance(subtask.parameters, dict) else {}

    if not job_id or job_id in PSEUDO_JOB_IDS:
        return Response({'status': 'Failed', 'message': f'No SLURM log for job_id={job_id}.'}, status=400)

    mapping_method = params.get('mapping_method') if subtask_type == 'scst_mapping' else None

    log_pattern = getattr(local_settings, 'SLURM_LOG_PATHS', {}).get((subtask_type, mapping_method))
    if not log_pattern:
        return Response({'status': 'Failed', 'message': f'No log path mapping for ({subtask_type}, {mapping_method}).'}, status=400)

    log_path = log_pattern.format(job_id=job_id)
    try:
        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()
        # --- Extract error-relevant lines ---
        import re
        # Patterns that indicate error context
        error_keywords = re.compile(
            r'(?i)(traceback|error|exception|failed|fatal|slurmstepd|'
            r'cannot|unable to|no such file|permission denied|'
            r'keyerror|valueerror|filenotfound|runtimeerror|'
            r'assertionerror|memoryerror|timeout|killed)'
        )
        # Collect error blocks: Traceback sections + keyword lines with context
        error_lines = []
        in_traceback = False
        for i, line in enumerate(lines):
            if 'Traceback (most recent call last):' in line:
                in_traceback = True
                error_lines.append(i)
                continue
            if in_traceback:
                # Traceback body: indented lines or the final error line
                if line.startswith(' ') or line.startswith('	') or line.strip() == '':
                    error_lines.append(i)
                else:
                    in_traceback = False
                    # Check if this is the final error line (non-indented, after traceback)
                    if error_keywords.search(line):
                        error_lines.append(i)
            elif error_keywords.search(line):
                # Add context: 2 lines before and after
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    if j not in error_lines:
                        error_lines.append(j)
        # Deduplicate and sort
        error_lines = sorted(set(error_lines))
        if error_lines:
            selected = [lines[i] for i in error_lines]
        else:
            # Fallback: last 30 lines
            selected = lines[-30:]
        log_content = ''.join(selected)
        # --- Sanitize sensitive paths ---
        log_content = re.sub(r'/data[23]/platform/\S+', '[DATA_PATH]', log_content)
        log_content = re.sub(r'/data[23]/\S+', '[DATA_PATH]', log_content)
        log_content = re.sub(r'/home/platform/\S+', '[PATH]', log_content)
        return Response({'status': 'Success', 'log': log_content})
    except FileNotFoundError:
        return Response({'status': 'Failed', 'message': 'Log file not found.'}, status=404)
    except Exception as e:
        return Response({'status': 'Failed', 'message': str(e)}, status=500)
