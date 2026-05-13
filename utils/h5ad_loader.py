import os
import anndata as ad
import numpy as np
from functools import lru_cache

# 缓存最近读取的 3 个文件，防止反复读硬盘
@lru_cache(maxsize=3)
def load_scatter_data(file_full_path):
    """
    只读取用于画图的坐标和元数据
    """
    if not os.path.exists(file_full_path):
        return None

    try:
        # backed='r' 是速度的关键，不把整个文件读入内存
        adata = ad.read_h5ad(file_full_path, backed='r')
        
        # 1. 找坐标 (UMAP / TSNE)
        keys = adata.obsm.keys()
        coords = None
        if 'X_umap' in keys: coords = adata.obsm['X_umap']
        elif 'X_tsne' in keys: coords = adata.obsm['X_tsne']
        
        if coords is None:
            return {}

        # 2. 找元数据 (Cluster, CellType, Donor)
        df = adata.obs.copy()
        
        # 数据清洗 (JSON 不支持 NaN)
        df = df.replace({np.nan: None})
        # 转换 category 为 str
        for col in df.select_dtypes(include=['category']).columns:
            df[col] = df[col].astype(str)

        # 3. 拼装结果
        # 格式: { "barcode1": {"x": 1.2, "y": 3.4, "cell_type": "T-Cell"}, ... }
        result = {}
        # 为了性能，这里使用 numpy 迭代
        obs_names = adata.obs_names
        obs_dict = df.to_dict(orient='index')
        
        for i, barcode in enumerate(obs_names):
            result[barcode] = {
                'x': float(coords[i][0]), # 确保是 float
                'y': float(coords[i][1]),
                **obs_dict[barcode]       # 合并 metadata
            }
            
        return result

    except Exception as e:
        print(f"Error loading h5ad: {e}")
        return None