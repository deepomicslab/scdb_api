import anndata
import numpy as np
import pandas as pd
from scipy import sparse

def get_spider_metadata(h5ad_path, top_n=10):
    """
    Interface 1: get overall metadata (which Patterns exist, and which LRs each Pattern has)
    """
    # Use backed='r' mode: opens instantly without consuming much memory
    adata = anndata.read_h5ad(h5ad_path, backed='r')
    
    metadata = []
    
    # 1. Confirm the number of Patterns
    if 'pattern_score' not in adata.obsm.keys():
        return {"error": "pattern_score not found in h5ad"}
        
    n_patterns = adata.obsm['pattern_score'].shape[1]
    
    # 2. Iterate to build the hierarchy
    for i in range(n_patterns):
        pattern_item = {
            "id": i,
            "name": f"Pattern {i}",
            "svis": []
        }
        
        # 3. Filter the LRs (SVIs) belonging to this Pattern
        # Note: in backed mode, adata.var can be read directly as a pandas DataFrame
        if 'label' in adata.var.columns:
            # Filter
            pattern_vars = adata.var[adata.var['label'] == i]
            
            # Sort (if a correlation field exists)
            corr_col = f'pattern_correlation_{i}'
            if corr_col in pattern_vars.columns:
                # Sort in descending order
                pattern_vars = pattern_vars.sort_values(by=corr_col, ascending=False)
            
            # Take the Top N
            top_vars = pattern_vars.head(top_n)
            
            # Assemble the LR list
            for lr_name, row in top_vars.iterrows():
                score = row.get(corr_col, 0)
                pattern_item['svis'].append({
                    "name": lr_name,
                    "score": round(float(score), 3)
                })
        
        metadata.append(pattern_item)
    
    # 4. Also extract the coordinates here (the frontend only needs this one call to init)
    # Assume coordinates live in obs['row'] and obs['col']
    coordinates = []
    if 'row' in adata.obs.columns and 'col' in adata.obs.columns:
        # Batch read for speed
        rows = adata.obs['row'].values
        cols = adata.obs['col'].values
        obs_names = adata.obs_names
        
        # Assemble the coordinates
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
    Interface 2: get the score data (color values) of a given Pattern
    pattern_id: int (e.g. 0, 1, 2)
    """
    adata = anndata.read_h5ad(h5ad_path, backed='r')
    
    try:
        pid = int(pattern_id)
        # Read a column from obsm
        # Note: in backed mode, reading obsm returns a numpy array
        scores = adata.obsm['pattern_score'][:, pid]
        
        # Convert to a list for return
        return scores.flatten().tolist()
    except Exception as e:
        print(f"Error reading pattern {pattern_id}: {e}")
        return []

def get_lr_data(h5ad_path, lr_name):
    """
    Interface 3: get the expression data of a given LR (ligand-receptor) pair
    lr_name: str (e.g. 'Egfr-Tgfa')
    """
    adata = anndata.read_h5ad(h5ad_path, backed='r')
    
    try:
        # 1. Check whether the name exists
        if lr_name not in adata.var_names:
            return []
            
        # 2. Get the whole column of data for this LR
        # The extraction method depends on whether the data is sparse
        # In backed mode, adata[:, 'name'].X usually handles partial IO automatically
        data_col = adata[:, lr_name].X
        
        # 3. Handle sparse matrices
        if sparse.issparse(data_col):
            values = data_col.toarray().flatten()
        else:
            values = data_col.flatten()
            
        return values.tolist()
    except Exception as e:
        print(f"Error reading LR {lr_name}: {e}")
        return []