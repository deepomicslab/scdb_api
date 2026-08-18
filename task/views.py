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
from utils.page import paginate_dataframe
from utils.fileprocess import get_gene_list,get_cluster_list
from utils.mapping_paths import check_mapping_completed
import pickle
from utils.spatial_calibration import IMAGE_RES_SPECS

# Maximum accepted h5ad upload size (bytes). Checked incrementally while streaming
# chunks to disk, so oversized uploads are aborted before they can fill /data3.
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

# HDF5 magic bytes: h5ad files are HDF5 containers and must start with this signature.
HDF5_MAGIC = b'\x89HDF\r\n\x1a\n'


def _is_h5ad_content(file_obj):
    """Cheap validation that the uploaded stream begins with the HDF5 signature.

    Reads the first 8 bytes of a freshly-written file; rewinds is not needed since
    the file is only read once after writing completes.
    """
    try:
        file_obj.seek(0)
        head = file_obj.read(len(HDF5_MAGIC))
        return head == HDF5_MAGIC
    except Exception:
        return False



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
    # create user task folder and save the file
    usertask_dir = str(int(time.time()))+'_' + str(random.randint(1000, 9999))
    userpath = local_settings.USERTASKPATH+usertask_dir
    uploadfilepath = userpath + '/upload/'
    os.makedirs(uploadfilepath, exist_ok=False)
    # file = request.FILES['submitfile']
    # default_storage.save(uploadfilepath+'input.h5ad', ContentFile(file.read()))
    # Make sure 'submitfile' is in request.FILES
    if 'submitfile' in request.FILES:
        upload_path = os.path.join(uploadfilepath, 'input.h5ad')
        try:
            file = request.FILES['submitfile']

            total = 0
            with open(upload_path, 'wb+') as destination:
                for chunk in file.chunks():
                    total += len(chunk)
                    if total > MAX_UPLOAD_SIZE:
                        raise ValueError(
                            f'File exceeds the maximum upload size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB'
                        )
                    destination.write(chunk)
                destination.flush()
                if not _is_h5ad_content(destination):
                    raise ValueError('Uploaded file is not a valid HDF5/h5ad file')
            print("File saved successfully:", uploadfilepath + 'input.h5ad')
        except ValueError as e:
            # delete the partial/oversized upload before responding
            if os.path.exists(upload_path):
                os.remove(upload_path)
            try:
                os.removedirs(uploadfilepath)  # removes upload/ and the task dir if empty
            except OSError:
                pass
            return Response({'status': 'Failed', 'message': str(e)}, status=400)
        except Exception as e:
            print("Upload error:", e)
            if os.path.exists(upload_path):
                os.remove(upload_path)
            return Response({'status': 'Failed', 'message': f'File upload failed: {str(e)}'}, status=500)

    else:
        # If the file is missing, return an error
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
    # No longer expose userpath / inputpath / outputpath (they contain server workspace paths)
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
        from utils.analysis import Scstquery
        module = Scstquery.__new__(Scstquery)
        res = module.gettestresult(query_params)
        return Response(res)
    try:
        taskobject = tasks.objects.get(id=taskid)
    except tasks.DoesNotExist:
        return Response({'status': 'error', 'message': 'Task not found'}, status=404)

    module = None
    jsonpath = local_settings.USERTASKPATH + taskobject.userpath + '/taskdetail.json'
    try:
        with open(jsonpath, 'r') as f:
            taskdetail = json.load(f)
        detail = taskdetail[0] if isinstance(taskdetail, list) else taskdetail
        modulename = detail.get('modulename')
        params = detail.get('parameters_dict', {})
        cls = get_module_class(modulename)
        if cls:
            module = cls(taskobject.name, taskobject.userpath, params)
    except Exception:
        pass

    if module is None:
        objectpath = local_settings.USERTASKPATH + taskobject.userpath + '/moduleobject.pkl'
        if os.path.exists(objectpath):
            with open(objectpath, 'rb') as f:
                module = pickle.load(f)
        else:
            return Response({'status': 'error', 'message': 'Task metadata not found'}, status=404)

    res=module.getresult(query_params)
    # scstmappingDownload returns a {'_stream_file': path, 'filename': ...} marker ->
    # stream the h5ad as a FileResponse instead of base64-encoding it into a JSON body
    # (avoids loading multi-MB files into memory + client-side atob churn).
    if isinstance(res, dict) and res.get('_stream_file'):
        return FileResponse(open(res['_stream_file'], 'rb'),
                            as_attachment=True,
                            filename=res.get('filename', 'mapping.h5ad'),
                            content_type='application/octet-stream')
    # scgpt image results return {'_image_file': path} -> inline image response
    # (attachment download would break direct <img> display). No-cache: re-runs
    # regenerate these PNGs under the same URL, so browsers must revalidate.
    if isinstance(res, dict) and res.get('_image_file'):
        return _img_file_response(
            res['_image_file'], 'image/png',
            cache_headers={'Cache-Control': 'no-cache'},
        )
    return Response(res)


# getImg browser cache: the URL is stable per dataset_id/resolution, and the image content
# does not change until the dataset is re-imported.
# max-age=86400 (1 day): after a dataset re-import, stale images lag at most 1 day
# (or until the user forces a refresh).
_IMG_CACHE_HEADERS = {'Cache-Control': 'public, max-age=86400'}


def _img_file_response(path, content_type, cache_headers=_IMG_CACHE_HEADERS):
    """Image FileResponse: explicit Content-Encoding: identity makes GZipMiddleware skip it.

    JPEG is already compressed; streaming gzip wastes CPU without reducing size. The
    identity header is Django's official mechanism for making GZipMiddleware skip a
    response (responses that already have Content-Encoding are not compressed again).

    cache_headers defaults to the long-lived dataset-image cache (stable per
    dataset_id/resolution). Analysis-result images (scgpt UMAP/heatmap, re-generated
    on every re-run) must pass a no-cache header instead so <img> revalidation
    always picks up the fresh PNG.
    """
    resp = FileResponse(open(path, 'rb'), content_type=content_type, headers=cache_headers)
    resp['Content-Encoding'] = 'identity'
    return resp


def _ensure_resolution_image(cache_path, hires_path, max_size, save_kwargs):
    """Ensure the target-resolution image exists and matches the current size constants,
    rebuilding it from hires.jpg by downscaling if not.

    - target = min(max_size, hires long edge) (when the source is smaller than the
      constant, the thumbnail is not upscaled);
    - if the current file's long edge deviates from target by >1px it is considered
      stale -> rebuild (no pixel decoding, only reads the header);
    - returns True when the file is usable (exists and matches size); False when it
      cannot be derived from hires.
    """
    import os
    from PIL import Image

    try:
        hw, hh = None, None
        if os.path.exists(hires_path):
            with Image.open(hires_path) as himg:
                hw, hh = himg.width, himg.height
        if not hw or not hh:
            return False

        if os.path.exists(cache_path):
            with Image.open(cache_path) as mimg:
                cur_long = max(mimg.width, mimg.height)
            target = min(max_size, max(hw, hh)) if max_size else max(hw, hh)
            if abs(cur_long - target) <= 1:
                return True
        elif max_size is None:
            # original tier: hires itself is the target
            return True

        # Rebuild: downscale hires.jpg (no pixel-array decoding, just LANCZOS resize + re-encode)
        with Image.open(hires_path) as himg:
            img = himg.copy()
            if max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            img.save(cache_path, 'JPEG', **save_kwargs)
        return True
    except Exception as e:
        print(f"[getImg] _ensure_resolution_image failed: {e}")
        return False


@api_view(['GET', 'HEAD'])
def getImg(request):
    image_analysis_type = request.query_params.get('image_analysis_type')
    image_id = request.query_params.get('image_id')
    # Optional resolution hint: 'thumbnail' returns a 400x400 max downscaled
    # JPEG (file name per IMAGE_RES_SPECS under MEDIA_ROOT/{image_dir}).
    # Default returns the full hires image (backwards compatible).
    resolution = request.query_params.get('resolution')

    if image_analysis_type == "he":
        from django.conf import settings
        from utils.spatial_calibration import pil_image_from_array

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

        # 3 resolution tiers (the spec table is the single source of truth):
        #   thumbnail : 400x400 JPEG q75  (~13KB)  - card thumbnail
        #   medium    : 800x800 JPEG q80  (~50-100KB) - scatter base image (default)
        #   original  : full-resolution JPEG q85 (~1MB) - high-res opt-in
        key = resolution if resolution in IMAGE_RES_SPECS else 'medium'
        filename, max_size, save_kwargs = IMAGE_RES_SPECS[key]
        content_type = 'image/jpeg'

        image_dir = ds.image_dir or f'st/{ds.dataset_id}'
        cache_path = os.path.join(settings.MEDIA_ROOT, image_dir, filename)
        hires_path = os.path.join(settings.MEDIA_ROOT, image_dir, 'hires.jpg')

        # Preferred path: validate/rebuild from hires.jpg (thumbnail/medium tiers;
        # automatically follows MEDIUM_MAX_SIZE changes)
        if _ensure_resolution_image(cache_path, hires_path, max_size, save_kwargs):
            if not ds.image_dir:
                Dataset.objects.filter(dataset_id=ds.dataset_id).update(
                    image_dir=f'st/{ds.dataset_id}'
                )
            return _img_file_response(cache_path, content_type)

        # Fallback: hires.jpg also missing -> extract the image from h5ad (self-healing path)
        if not os.path.exists(cache_path):
            # Extract: pull image from h5ad -> save to media -> self-healing write-back of image_dir
            try:
                import h5py
                from PIL import Image
                with h5py.File(ds.file_path, "r") as f:
                    if "uns/spatial" not in f:
                        return Response({'message': "No image for this dataset."}, status=404)
                    for lib in f["uns/spatial"].keys():
                        for img_key in ("hires", "lowres"):
                            img_full = f"uns/spatial/{lib}/images/{img_key}"
                            if img_full in f:
                                img = pil_image_from_array(f[img_full][:])
                                if max_size:
                                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                img.save(cache_path, 'JPEG', **save_kwargs)
                                if not ds.image_dir:
                                    # First extraction: write back image_dir so later requests read directly
                                    Dataset.objects.filter(dataset_id=ds.dataset_id).update(
                                        image_dir=f'st/{ds.dataset_id}'
                                    )
                                return _img_file_response(cache_path, content_type)
            except Exception as e:
                print(f"[getImg] error extracting image for {image_id}: {e}")
            return Response({'message': "No image for this dataset."}, status=404)

        return _img_file_response(cache_path, content_type)
    else:
        return Response({'message': f"No such analysis_type {image_analysis_type}"}, status=400)
    
@api_view(['POST'])
def create_subtask(request):
    """
    Create an scst subtask
    - taskid (main task ID)
    - userid
    - dataset_id (dataset ID, e.g. Kidney_Cancer_001)
    - subtasktype (subtask type)
    - parameters (JSON string)

    Note: the server path (dataset_path) sent by the client is no longer accepted;
    when a marker path is needed, the server looks it up by dataset_id to avoid
    path leakage/injection.
    """
    taskid = request.data.get('taskid')
    userid = request.data.get('userid')
    dataset_id = request.data.get('dataset_id', '')
    subtasktype = request.data.get('subtasktype')

    if not taskid or not userid or not dataset_id or not subtasktype:
        return Response({'status': 'Failed', 'message': 'Missing taskid, userid, dataset_id or subtasktype'}, status=400)

    try:
        main_task = tasks.objects.get(id=taskid, user=userid)
    except tasks.DoesNotExist:
        return Response({'status': 'Failed', 'message': 'Task not found'}, status=404)

    parameters_string = request.data.get('parameters')
    if not parameters_string:
        return Response({'status': 'Failed', 'message': 'Missing parameters'}, status=400)
    try:
        parameters_dict = json.loads(parameters_string)
    except (json.JSONDecodeError, TypeError) as e:
        return Response({'status': 'Failed', 'message': f'Invalid parameters JSON: {str(e)}'}, status=400)

    try:
        result = create_subtask_service(main_task, userid, dataset_id, subtasktype, parameters_dict)
        return Response(result)
    except ValueError as e:
        traceback.print_exc()
        return Response({'status': 'Failed', 'message': str(e)}, status=400)
    except Exception as e:
        traceback.print_exc()
        return Response({'status': 'Failed', 'message': f'Subtask creation failed: {str(e)}'})

# view.py
@api_view(['GET'])
def subtask_status_update(request):
    """
    Fetch and update a subtask's live status on demand (does not depend on the PKL file).
    Parameters: subtaskid
    """
    subtaskid = request.query_params.get('subtaskid')

    if not subtaskid:
        return Response({'status': 'Failed', 'message': 'Missing subtaskid parameter.'}, status=400)

    try:
        subtask = SubTask.objects.get(id=subtaskid)
    except SubTask.DoesNotExist:
        return Response({'status': 'Failed', 'message': f'Subtask with ID {subtaskid} not found.'}, status=404)

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

    # 2d. Pending viewer waiting for scgpt_embedding subtask to complete
    # (UMAP/Heatmap embeddings share one scgpt_embedding compute job)
    if job_id == 'pending_scgpt' and subtask.subtask_type in ('umap_embedding', 'heatmap_embedding'):
        scgpt_subtask = SubTask.objects.filter(
            main_task=subtask.main_task,
            subtask_type='scgpt_embedding',
            dataset_path=subtask.dataset_path
        ).order_by('-id').first()
        _sync_dependency_from_slurm(scgpt_subtask)
        if scgpt_subtask and (scgpt_subtask.status or '').upper() == 'COMPLETED':
            subtask.status = TaskStatus.COMPLETED
            subtask.job_id = 'viewer_only'
            subtask.save()
            return Response({
                'status': 'Success',
                'current_status': TaskStatus.COMPLETED,
                'job_id': 'viewer_only',
                'message': 'scGPT embedding completed, viewer ready.'
            })
        scgpt_job = (subtask.parameters or {}).get('_scgpt_job_id', 'unknown')
        return Response({
            'status': 'Success',
            'current_status': 'Pending',
            'job_id': job_id,
            'scgpt_job_id': scgpt_job,
            'message': f'Waiting for scGPT embedding subtask (job {scgpt_job}) to complete.'
        })

    # 3. job_id is empty but status is non-terminal
    if not job_id:
        return Response({
            'status': 'Success',
            'current_status': current_db_status,
            'message': 'Task job ID missing.'
        })

    # 4. Query SLURM and update
    try:
        raw_status = slurm_api.get_job_status(job_id)
        if not raw_status:
            return Response({
                'status': 'Success',
                'current_status': current_db_status,
                'job_id': job_id,
                'message': 'SLURM status temporarily unavailable, keeping the current status.'
            })

        new_status = normalize_slurm_status(raw_status)

        if new_status != current_db_status:
            subtask.status = new_status
            subtask.save()

        return Response({
            'status': 'Success',
            'current_status': new_status,
            'job_id': job_id,
            'message': f'Status updated to {new_status}'
        })

    except Exception as e:
        traceback.print_exc()
        return Response({'status': 'Failed', 'message': f'Failed to query SLURM status: {str(e)}'}, status=500)
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
        try:
            with open(log_path, 'r', errors='replace') as f:
                lines = f.readlines()
        except FileNotFoundError:
            # For lr_comparison, fallback to CellChat job logs
            if subtask_type == 'lr_comparison':
                cellchat_log_pattern = getattr(local_settings, 'SLURM_LOG_PATHS', {}).get(('cellchat', None))
                if cellchat_log_pattern:
                    cellchat_lines = []
                    for key in ('_sc_cellchat_job_id', '_st_cellchat_job_id'):
                        cj = params.get(key)
                        if cj:
                            try:
                                cellchat_log_path = cellchat_log_pattern.format(job_id=cj)
                                with open(cellchat_log_path, 'r', errors='replace') as f:
                                    cellchat_lines.append("=== CellChat job %s log ===\n" % cj)
                                    cellchat_lines.extend(f.readlines()[-30:])
                                    cellchat_lines.append("\n")
                            except (FileNotFoundError, OSError):
                                pass
                    if cellchat_lines:
                        log_content = ''.join(cellchat_lines)
                        import re
                        log_content = re.sub(r'/data[23]/platform/\S+', '[DATA_PATH]', log_content)
                        log_content = re.sub(r'/data[23]/\S+', '[DATA_PATH]', log_content)
                        log_content = re.sub(r'/home/platform/\S+', '[PATH]', log_content)
                        return Response({'status': 'Success', 'log': log_content})
            return Response({'status': 'Failed', 'message': 'Log file not found.'}, status=404)

        # --- Extract error-relevant lines ---
        import re
        error_keywords = re.compile(
            r'(?i)(traceback|error|exception|failed|fatal|slurmstepd|'
            r'cannot|unable to|no such file|permission denied|'
            r'keyerror|valueerror|filenotfound|runtimeerror|'
            r'assertionerror|memoryerror|timeout|killed)'
        )
        error_lines = []
        in_traceback = False
        for i, line in enumerate(lines):
            if 'Traceback (most recent call last):' in line:
                in_traceback = True
                error_lines.append(i)
                continue
            if in_traceback:
                if line.startswith(' ') or line.startswith('\t') or line.strip() == '':
                    error_lines.append(i)
                else:
                    in_traceback = False
                    if error_keywords.search(line):
                        error_lines.append(i)
            elif error_keywords.search(line):
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    if j not in error_lines:
                        error_lines.append(j)
        error_lines = sorted(set(error_lines))
        if error_lines:
            selected = [lines[i] for i in error_lines]
        else:
            selected = lines[-30:]
        log_content = ''.join(selected)
        log_content = re.sub(r'/data[23]/platform/\S+', '[DATA_PATH]', log_content)
        log_content = re.sub(r'/data[23]/\S+', '[DATA_PATH]', log_content)
        log_content = re.sub(r'/home/platform/\S+', '[PATH]', log_content)
        return Response({'status': 'Success', 'log': log_content})

    except Exception as e:
        return Response({'status': 'Failed', 'message': str(e)}, status=500)
