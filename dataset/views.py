from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import FileResponse
from django.db.models import Count, Sum, Q
import os
import time
import numpy as np
import pandas as pd
from collections import Counter
import scanpy as sc

from .models import Dataset, GlobalStat

# ================================
# 1. 全局统计 (Hero Stats) - 极快
# ================================
@api_view(['GET'])
def global_stats(request):
    """
    对应页面顶部的 4 个大数字
    """
    gs = GlobalStat.objects.first()
    
    if gs:
        data = {
            'total_spots': gs.total_spots,
            'total_datasets': gs.total_datasets,
            'total_donors': gs.total_donors,
            'total_organs': gs.total_organs,
        }
    else:
        data = {
            'total_spots': 0, 'total_datasets': 0, 
            'total_donors': 0, 'total_organs': 0
        }
    
    return Response({'status': 'success', 'data': data})

# ================================
# 2. 器官统计 (Organ List & Charts) - SQL 聚合
# ================================
@api_view(['GET'])
def organ_stats(request):
    rows = (
        Dataset.objects
        .values('organ')
        .annotate(
            datasets=Count('id'),
            spots=Sum('n_spots'),
            donors=Sum('n_donors'),
            normal_donors=Sum('n_donors', filter=Q(disease='Normal')),
            disease_donors=Sum('n_donors', filter=~Q(disease='Normal')),
        )
        .order_by('organ')
    )

    agg_result = {}
    for row in rows:
        organ = row['organ'] or 'Unknown'
        agg_result[organ] = {
            'datasets': row['datasets'],
            'spots': row['spots'] or 0,
            'donors': row['donors'] or 0,
            'normal_donors': row['normal_donors'] or 0,
            'disease_donors': row['disease_donors'] or 0,
        }

    return Response({'status': 'success', 'data': agg_result})

# ================================
# 3. 数据集表格 (Table List) - 较慢
# ================================
@api_view(['GET'])
def dataset_list(request):
    """
    返回底部表格的完整数据
    """
    datasets = Dataset.objects.all().values(
        'dataset_id', 
        'title', 
        'organ',
        'disease', 
        'n_spots', 
        'n_donors',
        'citation_label',
        'citation_url',
        'collection_url',
        'explorer_url', 
        'created_at'
    ).order_by('created_at')
    
    return Response({'status': 'success', 'data': list(datasets)})

# ================================
# 4. 细胞类型统计 (饼图) - 带缓存
# ================================
_celltype_cache = {}
_celltype_cache_time = {}
_CELLTYPE_CACHE_TTL = 60


@api_view(['GET'])
def celltype_stats(request):
    target_organ = request.GET.get('organ', 'All') or 'All'
    cache_key = target_organ.lower()

    now = time.time()
    if cache_key in _celltype_cache and (now - _celltype_cache_time.get(cache_key, 0)) < _CELLTYPE_CACHE_TTL:
        return Response({'status': 'success', 'data': _celltype_cache[cache_key]})

    if target_organ != 'All':
        counts_list = Dataset.objects.filter(organ__iexact=target_organ).values_list('cell_type_counts', flat=True)
    else:
        counts_list = Dataset.objects.values_list('cell_type_counts', flat=True)

    global_counter = Counter()
    for counts in counts_list:
        if counts:
            global_counter.update(counts)

    result_list = [{'name': k, 'value': v} for k, v in global_counter.items()]
    result_list.sort(key=lambda x: x['value'], reverse=True)

    if len(result_list) > 10:
        top_10 = result_list[:10]
        others_count = sum(item['value'] for item in result_list[10:])
        top_10.append({'name': 'Others', 'value': others_count})
        result_list = top_10

    _celltype_cache[cache_key] = result_list
    _celltype_cache_time[cache_key] = now

    return Response({'status': 'success', 'data': result_list})

# ================================
# 5. 详情页 Info (保持不变)
# ================================
@api_view(['GET'])
def detail_info(request, dataset_id):
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
        return Response({
            'status': 'success',
            'data': {
                'dataset_id': ds.dataset_id,
                'title': ds.title,
                'organ': ds.organ,
                'disease': ds.disease,
                'description': ds.description,
                'n_spots': ds.n_spots,
                'n_donors': ds.n_donors,
            }
        })
    except Dataset.DoesNotExist:
        return Response({'status': 'error', 'message': 'Dataset not found'}, status=404)

# ================================
# 6. 详情页 Scatter (向量化 + 长 TTL 缓存)
# ================================
_scatter_cache = {}
_SCATTER_CACHE_TTL = 3600


def _scatter_first_truthy(df, cols):
    s = None
    for c in cols:
        if c in df.columns:
            v = df[c].replace('', np.nan)
            s = v if s is None else s.fillna(v)
    if s is None:
        return pd.Series('Unknown', index=df.index)
    return s.fillna('Unknown')


@api_view(['GET'])
def detail_scatter(request, dataset_id):
    try:
        now = time.time()
        cached = _scatter_cache.get(dataset_id)
        if cached and cached[1] > now:
            return Response(cached[0])

        ds = Dataset.objects.get(dataset_id=dataset_id)
        file_path = ds.file_path

        if not os.path.exists(file_path):
            return Response({'status': 'error', 'message': 'File not found'}, status=404)

        adata = sc.read_h5ad(file_path, backed='r')
        
        coords = None
        coord_type = 'spatial'
        if 'spatial' in adata.obsm.keys():
            coords = adata.obsm['spatial']
        elif 'X_spatial' in adata.obsm.keys():
            coords = adata.obsm['X_spatial']
        elif 'X_umap' in adata.obsm.keys():
            coords = adata.obsm['X_umap']
            coord_type = 'umap'
            
        if coords is None:
            return Response({'status': 'error', 'message': 'No coordinates found'}, status=500)

        tissue_hires_scalef = None
        spot_diameter_fullres = None
        if coord_type == 'spatial' and 'spatial' in adata.uns:
            try:
                lib = next(iter(adata.uns['spatial'].keys()))
                sf = adata.uns['spatial'][lib].get('scalefactors', {})
                if 'tissue_hires_scalef' in sf:
                    tissue_hires_scalef = float(sf['tissue_hires_scalef'])
                if 'spot_diameter_fullres' in sf:
                    spot_diameter_fullres = float(sf['spot_diameter_fullres'])
            except Exception:
                pass

        target_cols = ['cell_type', 'annotation', 'Label', 'donor', 'donor_id', 'tissue']
        available_cols = [c for c in target_cols if c in adata.obs.columns]
        df = adata.obs[available_cols].copy()

        for col in df.columns:
            if pd.api.types.is_categorical_dtype(df[col]):
                df[col] = df[col].astype(str)
            df[col] = df[col].fillna('Unknown')
        if available_cols:
            df[available_cols] = df[available_cols].astype(str)

        if hasattr(coords, 'to_numpy'):
            coords = coords.to_numpy()
        coords = np.asarray(coords)

        if 'Label' in df.columns:
            label_series = df['Label']
        else:
            label_series = _scatter_first_truthy(df, ['cell_type', 'annotation', 'Label'])
        if 'donor' in df.columns:
            donor_series = df['donor']
        else:
            donor_series = _scatter_first_truthy(df, ['donor_id', 'donor'])

        df['x'] = coords[:, 0].astype(float)
        df['y'] = coords[:, 1].astype(float)
        df['Label'] = label_series
        df['donor'] = donor_series
        df.index = df.index.astype(str)

        data_dict = df.to_dict(orient='index')

        body = {
            'status': 'success',
            'data': data_dict,
            'coord_type': coord_type,
            'tissue_hires_scalef': tissue_hires_scalef,
            'spot_diameter_fullres': spot_diameter_fullres,
        }
        _scatter_cache[dataset_id] = (body, time.time() + _SCATTER_CACHE_TTL)
        return Response(body)

    except Exception as e:
        print(e)
        return Response({'status': 'error', 'message': str(e)}, status=500)
    

# ================================
# 7. 下载 H5AD 文件接口 (新增)
# ================================
@api_view(['GET'])
def download_h5ad(request, dataset_id):
    """
    流式下载 .h5ad 文件
    """
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
        file_path = ds.file_path
        
        if not os.path.exists(file_path):
            return Response({'status': 'error', 'message': 'File not found on server'}, status=404)

        # 打开文件句柄
        # FileResponse 会自动关闭文件，并处理 Content-Length 等头信息
        file_handle = open(file_path, 'rb')
        response = FileResponse(file_handle)
        
        # 设置下载的文件名 (浏览器下载时显示的名字)
        # 这里默认用 {dataset_id}.h5ad
        filename = f"{ds.dataset_id}.h5ad"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response

    except Dataset.DoesNotExist:
        return Response({'status': 'error', 'message': 'Dataset ID not found'}, status=404)
    except Exception as e:
        return Response({'status': 'error', 'message': str(e)}, status=500)