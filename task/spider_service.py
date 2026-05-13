import anndata
import numpy as np
import pandas as pd
from scipy import sparse

def get_spider_metadata(h5ad_path, top_n=10):
    """
    接口1：获取总的元数据（有哪些 Pattern，每个 Pattern 下有哪些 LR）
    """
    # 使用 backed='r' 模式，秒开，不占用大量内存
    adata = anndata.read_h5ad(h5ad_path, backed='r')
    
    metadata = []
    
    # 1. 确认 Pattern 数量
    if 'pattern_score' not in adata.obsm.keys():
        return {"error": "pattern_score not found in h5ad"}
        
    n_patterns = adata.obsm['pattern_score'].shape[1]
    
    # 2. 遍历构建层级结构
    for i in range(n_patterns):
        pattern_item = {
            "id": i,
            "name": f"Pattern {i}",
            "svis": []
        }
        
        # 3. 筛选属于该 Pattern 的 LR (SVI)
        # 注意：backed 模式下 adata.var 是可以直接读取的 pandas DataFrame
        if 'label' in adata.var.columns:
            # 筛选
            pattern_vars = adata.var[adata.var['label'] == i]
            
            # 排序 (如果有相关性字段)
            corr_col = f'pattern_correlation_{i}'
            if corr_col in pattern_vars.columns:
                # 降序排列
                pattern_vars = pattern_vars.sort_values(by=corr_col, ascending=False)
            
            # 取 Top N
            top_vars = pattern_vars.head(top_n)
            
            # 组装 LR 列表
            for lr_name, row in top_vars.iterrows():
                score = row.get(corr_col, 0)
                pattern_item['svis'].append({
                    "name": lr_name,
                    "score": round(float(score), 3)
                })
        
        metadata.append(pattern_item)
    
    # 4. 同时顺便把坐标也提取出来（前端初始化只需要调这一次接口）
    # 假设坐标存在 obs['row'] 和 obs['col']
    coordinates = []
    if 'row' in adata.obs.columns and 'col' in adata.obs.columns:
        # 批量获取，速度快
        rows = adata.obs['row'].values
        cols = adata.obs['col'].values
        obs_names = adata.obs_names
        
        # 组装坐标
        for idx, name in enumerate(obs_names):
            coordinates.append({
                "id": name,
                "x": float(rows[idx]),
                "y": float(cols[idx])
            })
            
    return {
        "metadata": metadata,
        "coordinates": coordinates
    }

def get_pattern_data(h5ad_path, pattern_id):
    """
    接口2：获取指定 Pattern 的评分数据 (颜色值)
    pattern_id: int (例如 0, 1, 2)
    """
    adata = anndata.read_h5ad(h5ad_path, backed='r')
    
    try:
        pid = int(pattern_id)
        # 读取 obsm 中的某一列
        # 注意：backed 模式下，读取 obsm 会返回 numpy array
        scores = adata.obsm['pattern_score'][:, pid]
        
        # 转换为 list 返回
        return scores.flatten().tolist()
    except Exception as e:
        print(f"Error reading pattern {pattern_id}: {e}")
        return []

def get_lr_data(h5ad_path, lr_name):
    """
    接口3：获取指定 LR (配体-受体) 的表达数据
    lr_name: str (例如 'Egfr-Tgfa')
    """
    adata = anndata.read_h5ad(h5ad_path, backed='r')
    
    try:
        # 1. 检查名字是否存在
        if lr_name not in adata.var_names:
            return []
            
        # 2. 获取该 LR 对应的整列数据
        # 这里的提取方式取决于数据是否稀疏
        # 在 backed 模式下，adata[:, 'name'].X 通常会自动处理部分 IO
        data_col = adata[:, lr_name].X
        
        # 3. 处理稀疏矩阵
        if sparse.issparse(data_col):
            values = data_col.toarray().flatten()
        else:
            values = data_col.flatten()
            
        return values.tolist()
    except Exception as e:
        print(f"Error reading LR {lr_name}: {e}")
        return []