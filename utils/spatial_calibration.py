import os
import h5py
from dataset.models import Dataset


MEDIUM_MAX_SIZE = 800


def premultiply_coords(data, scalef):
    """Recursively multiply all x/y coordinate values by scalef.

    Traverses dicts and lists to find all objects with x and y keys at any
    nesting level. Handles both float and string-encoded numeric values.
    Returns the modified data (mutates in place for lists; dicts are also
    mutated in place since they are mutable).
    """
    if not scalef or scalef == 1.0:
        return data

    if isinstance(data, dict):
        if 'x' in data and 'y' in data:
            try:
                data['x'] = float(data['x']) * scalef
                data['y'] = float(data['y']) * scalef
            except (ValueError, TypeError):
                pass
            return data
        for k, v in data.items():
            data[k] = premultiply_coords(v, scalef)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            data[i] = premultiply_coords(item, scalef)

    return data


def read_spatial_calibration(dataset_id):
    """Read (tissue_hires_scalef, spot_diameter_fullres) from a dataset's h5ad.

    Returns a tuple (scalef, spot); each element is a float when the matching
    key exists under uns/spatial/{lib}/scalefactors, otherwise None.

    The returned scalef is adjusted to match the medium-resolution image
    (MEDIUM_MAX_SIZE px, as served by getImg by default) rather than the raw
    scalef from the h5ad. This ensures VizPanel's coordinate formula
    (d.x * scalef * imageScale) works correctly with medium images.

    The adjustment follows the same image-source priority as getImg
    (hires -> lowres) so the scalef always matches the actual image being
    served, regardless of whether the medium image was derived from hires
    or lowres.

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
            if uns_spatial is None:
                return scalef, spot
            libs = list(uns_spatial.keys())
            if not libs:
                return scalef, spot

            lib = libs[0]

            # Read spot_diameter_fullres (always from scalefactors)
            spot_key = f'uns/spatial/{lib}/scalefactors/spot_diameter_fullres'
            if spot_key in f:
                try:
                    spot = float(f[spot_key][()])
                except Exception:
                    spot = None

            # Determine image source with same priority as getImg (hires -> lowres),
            # read the corresponding scalefactor and image dimensions, then
            # adjust scalef to medium space.
            for img_key, scalefactor_key in [
                ('hires', 'tissue_hires_scalef'),
                ('lowres', 'tissue_lowres_scalef'),
            ]:
                img_path = f'uns/spatial/{lib}/images/{img_key}'
                if img_path not in f:
                    continue

                # Read the scalefactor for this image source
                sf_key = f'uns/spatial/{lib}/scalefactors/{scalefactor_key}'
                if sf_key in f:
                    try:
                        scalef = float(f[sf_key][()])
                    except Exception:
                        pass
                elif scalef is None:
                    # Fallback for lowres when tissue_lowres_scalef is missing
                    sf_key = f'uns/spatial/{lib}/scalefactors/tissue_hires_scalef'
                    if sf_key in f:
                        try:
                            scalef = float(f[sf_key][()])
                        except Exception:
                            pass

                # Read image dimensions and compute medium ratio
                try:
                    arr = f[img_path]
                    img_h, img_w = arr.shape[0], arr.shape[1]
                    if scalef is not None:
                        medium_ratio = min(MEDIUM_MAX_SIZE / img_w, MEDIUM_MAX_SIZE / img_h)
                        scalef = scalef * medium_ratio
                except Exception:
                    pass

                break  # First found image wins (hires -> lowres priority)

    except Exception as e:
        print(f'[read_spatial_calibration] error for {dataset_id}: {e}')

    return scalef, spot
