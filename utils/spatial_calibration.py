import os
import h5py
from dataset.models import Dataset


def read_spatial_calibration(dataset_id):
    """Read (tissue_hires_scalef, spot_diameter_fullres) from a dataset's h5ad.

    Returns a tuple (scalef, spot); each element is a float when the matching
    key exists under uns/spatial/{lib}/scalefactors, otherwise None.

    No numeric fallback is applied here: a missing scalef/spot cannot be
    invented safely because the correct fallback depends on the coordinate
    convention (fullres vs pre-multiplied hires), which only the caller/frontend
    knows. Callers should pass None through and let the frontend decide.
    """
    if not dataset_id:
        return None, None
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
    except Dataset.DoesNotExist:
        return None, None

    file_path = ds.file_path
    if not file_path or not os.path.exists(file_path):
        return None, None

    scalef = None
    spot = None
    try:
        with h5py.File(file_path, 'r') as f:
            uns_spatial = f.get('uns/spatial')
            if uns_spatial is not None:
                libs = list(uns_spatial.keys())
                if libs:
                    lib = libs[0]
                    scalef_key = f'uns/spatial/{lib}/scalefactors/tissue_hires_scalef'
                    spot_key = f'uns/spatial/{lib}/scalefactors/spot_diameter_fullres'
                    if scalef_key in f:
                        try:
                            scalef = float(f[scalef_key][()])
                        except Exception:
                            scalef = None
                    if spot_key in f:
                        try:
                            spot = float(f[spot_key][()])
                        except Exception:
                            spot = None
    except Exception as e:
        print(f'[read_spatial_calibration] error for {dataset_id}: {e}')

    return scalef, spot
