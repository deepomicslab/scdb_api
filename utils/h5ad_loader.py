import os
import anndata as ad
import numpy as np
from functools import lru_cache

# Cache the 3 most recently read files to avoid repeated disk reads
@lru_cache(maxsize=3)
def load_scatter_data(file_full_path):
    """
    Only read the coordinates and metadata needed for plotting
    """
    if not os.path.exists(file_full_path):
        return None

    try:
        # backed='r' is the key to speed: it does not load the whole file into memory
        adata = ad.read_h5ad(file_full_path, backed='r')
        
        # 1. Find the coordinates (UMAP / TSNE)
        keys = adata.obsm.keys()
        coords = None
        if 'X_umap' in keys: coords = adata.obsm['X_umap']
        elif 'X_tsne' in keys: coords = adata.obsm['X_tsne']
        
        if coords is None:
            return {}

        # 2. Find the metadata (Cluster, CellType, Donor)
        df = adata.obs.copy()
        
        # Data cleaning (JSON does not support NaN)
        df = df.replace({np.nan: None})
        # Convert categories to str
        for col in df.select_dtypes(include=['category']).columns:
            df[col] = df[col].astype(str)

        # 3. Assemble the result
        # Format: { "barcode1": {"x": 1.2, "y": 3.4, "cell_type": "T-Cell"}, ... }
        result = {}
        # Iterate with numpy for performance
        obs_names = adata.obs_names
        obs_dict = df.to_dict(orient='index')
        
        for i, barcode in enumerate(obs_names):
            result[barcode] = {
                'x': float(coords[i][0]), # make sure it is a float
                'y': float(coords[i][1]),
                **obs_dict[barcode]       # merge the metadata
            }
            
        return result

    except Exception as e:
        print(f"Error loading h5ad: {e}")
        return None