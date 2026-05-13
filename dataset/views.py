from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import FileResponse # <--- 记得加这个引用
from django.db.models import Count
import os
import pandas as pd
from collections import Counter
import scanpy as sc

# 引入你的模型
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
# 2. 器官统计 (Organ List & Charts) - 快
# ================================
@api_view(['GET'])
def organ_stats(request):
    """
    返回按器官分组的统计数据，用于左侧列表和柱状图
    """
    # 获取计算所需字段
    qs = Dataset.objects.all().values('organ', 'disease', 'n_spots', 'n_donors')
    df = pd.DataFrame(list(qs))

    if df.empty:
        return Response({'status': 'success', 'data': {}})

    # 数据清洗
    df['organ'] = df['organ'].fillna('Unknown')
    df['n_spots'] = df['n_spots'].fillna(0).astype(int)
    df['n_donors'] = df['n_donors'].fillna(0).astype(int)
    
    # 标记 Normal
    df['is_normal'] = df['disease'] == 'Normal'
    
    agg_result = {}
    
    # Pandas 分组计算
    for organ, group in df.groupby('organ'):
        agg_result[organ] = {
            'datasets': len(group),
            'spots': int(group['n_spots'].sum()),
            'donors': int(group['n_donors'].sum()),
            # 计算 Normal 和 Disease 的 donor 分布
            'normal_donors': int(group[group['is_normal']]['n_donors'].sum()),
            'disease_donors': int(group[~group['is_normal']]['n_donors'].sum())
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
# 4. 细胞类型统计 (饼图) - 保持不变
# ================================
@api_view(['GET'])
def celltype_stats(request):
    target_organ = request.GET.get('organ', 'All')
    
    if target_organ and target_organ != 'All':
        datasets = Dataset.objects.filter(organ__iexact=target_organ)
    else:
        datasets = Dataset.objects.all()

    global_counter = Counter()
    for ds in datasets:
        if ds.cell_type_counts:
            global_counter.update(ds.cell_type_counts)
            
    result_list = [{'name': k, 'value': v} for k, v in global_counter.items()]
    result_list.sort(key=lambda x: x['value'], reverse=True)
    
    if len(result_list) > 10:
        top_10 = result_list[:10]
        others_count = sum(item['value'] for item in result_list[10:])
        top_10.append({'name': 'Others', 'value': others_count})
        result_list = top_10

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
# 6. 详情页 Scatter (保持不变)
# ================================
@api_view(['GET'])
def detail_scatter(request, dataset_id):
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
        file_path = ds.file_path
        
        if not os.path.exists(file_path):
            return Response({'status': 'error', 'message': 'File not found'}, status=404)

        adata = sc.read_h5ad(file_path, backed='r')
        
        coords = None
        if 'spatial' in adata.obsm.keys():
            coords = adata.obsm['spatial']
        elif 'X_spatial' in adata.obsm.keys():
            coords = adata.obsm['X_spatial']
        elif 'X_umap' in adata.obsm.keys():
            coords = adata.obsm['X_umap']
            
        if coords is None:
            return Response({'status': 'error', 'message': 'No coordinates found'}, status=500)

        target_cols = ['cell_type', 'annotation', 'Label', 'donor', 'donor_id', 'tissue']
        available_cols = [c for c in target_cols if c in adata.obs.columns]
        df = adata.obs[available_cols].copy()
        
        for col in df.columns:
            if pd.api.types.is_categorical_dtype(df[col]):
                df[col] = df[col].astype(str)
            df[col] = df[col].fillna('Unknown')

        data_dict = {}
        if hasattr(coords, "to_numpy"):
            coords = coords.to_numpy()
            
        indices = adata.obs.index
        # 如果点太多，建议在这里切片，例如 [:10000]
        
        for i, idx in enumerate(indices):
            meta = df.iloc[i].to_dict()
            label_val = meta.get('cell_type') or meta.get('annotation') or meta.get('Label') or 'Unknown'
            donor_val = meta.get('donor_id') or meta.get('donor') or 'Unknown'
            
            data_dict[str(idx)] = {
                'x': float(coords[i][0]),
                'y': float(coords[i][1]),
                'Label': str(label_val), 
                'donor': str(donor_val),
                **{k: str(v) for k,v in meta.items()} 
            }

        return Response({'status': 'success', 'data': data_dict})

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