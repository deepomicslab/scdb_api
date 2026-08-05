import os
import h5py
from PIL import Image
from django.conf import settings
from dataset.models import Dataset


# Image resolution constants (adjustable at any time: getImg rebuilds automatically
# from the new values when it detects the actual file does not match)
MEDIUM_MAX_SIZE = 800
THUMBNAIL_MAX_SIZE = 400

# Image spec table (single source of truth): resolution -> (file name, max size, save kwargs)
# Shared by getImg and Dataset._extract_images; max_size=None means original size (hires)
IMAGE_RES_SPECS = {
    'thumbnail': ('thumbnail.jpg', THUMBNAIL_MAX_SIZE, {'quality': 75, 'optimize': True}),
    'medium': ('medium.jpg', MEDIUM_MAX_SIZE, {'quality': 80, 'optimize': True}),
    'original': ('hires.jpg', None, {'quality': 85, 'optimize': True}),
}


def pil_image_from_array(arr):
    """h5ad image array -> PIL Image writable as JPEG.

    JPEG does not support RGBA/alpha modes: transparent images are composited onto
    a white background first; other unusual modes are converted to RGB.
    """
    img = Image.fromarray(arr)
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    return img


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


def extract_spatial_calibration(file_path):
    """Extract the raw spatial calibration values from h5ad.

    Returns (scalef_raw, spot):
      - scalef_raw: the raw scalef not multiplied by any ratio (resolved with
        hires -> lowres priority)
      - spot: spot_diameter_fullres

    Matches the getImg image-source priority (hires -> lowres), so the scalef
    always corresponds to the image actually served. The medium-space conversion
    is computed on the fly by read_spatial_calibration from the actual file
    dimensions (plan B).
    """
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

            # Library selection: skip scalar flags (e.g. is_single), take the first
            # Group containing images/scalefactors
            lib = None
            for candidate in libs:
                node = f.get(f'uns/spatial/{candidate}')
                if isinstance(node, h5py.Group) and ('images' in node or 'scalefactors' in node):
                    lib = candidate
                    break
            if lib is None:
                return scalef, spot

            spot_key = f'uns/spatial/{lib}/scalefactors/spot_diameter_fullres'
            if spot_key in f:
                try:
                    spot = float(f[spot_key][()])
                except Exception:
                    spot = None

            for img_key, scalefactor_key in [
                ('hires', 'tissue_hires_scalef'),
                ('lowres', 'tissue_lowres_scalef'),
            ]:
                img_path = f'uns/spatial/{lib}/images/{img_key}'
                if img_path not in f:
                    continue

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

                break  # First found image wins (hires -> lowres priority)

    except Exception as e:
        print(f'[extract_spatial_calibration] error for {file_path}: {e}')

    return scalef, spot


def _jpeg_dimensions(path):
    """Read the JPEG header dimensions (without decoding pixels); returns (None, None) on failure."""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def read_spatial_calibration(dataset_id):
    """Read (tissue_hires_scalef, spot_diameter_fullres) for a dataset.

    DB-first: scalef_raw/spot_diameter_fullres are extracted into the DB at
    import/backfill time. Medium-space conversion (plan B): the ratio is computed
    from the real dimensions of the served medium.jpg / hires.jpg
    (ratio = medium_w / hires_w), always matching the image getImg actually
    serves - MEDIUM_MAX_SIZE can change at any time, and the ratio catches up
    automatically once the image is rebuilt, with no misalignment window.

    Self-healing when fields are missing (pre-migration data / new imports not
    backfilled): extract from h5ad and write back to the database.
    """
    if not dataset_id:
        return None, None
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
    except Dataset.DoesNotExist:
        return None, None

    scalef_raw = ds.scalef_raw
    spot = ds.spot_diameter_fullres

    if scalef_raw is None:
        # Self-healing: field missing -> extract from h5ad and write back
        scalef_raw, spot = extract_spatial_calibration(ds.file_path)
        if scalef_raw is None:
            return None, None
        Dataset.objects.filter(dataset_id=dataset_id).update(
            scalef_raw=scalef_raw,
            spot_diameter_fullres=spot,
        )

    # ratio from the actual file dimensions (plan B); when files are missing,
    # fall back to the hires long edge + the constant
    medium_path = os.path.join(settings.MEDIA_ROOT, ds.image_dir, 'medium.jpg')
    hires_path = os.path.join(settings.MEDIA_ROOT, ds.image_dir, 'hires.jpg')
    mw, _mh = _jpeg_dimensions(medium_path)
    hw, hh = _jpeg_dimensions(hires_path)
    if mw and hw:
        medium_ratio = mw / hw
    elif hw and hh:
        # Fallback: when medium.jpg is missing, estimate from the hires long edge + constant
        medium_ratio = min(MEDIUM_MAX_SIZE / hw, MEDIUM_MAX_SIZE / hh)
    else:
        medium_ratio = 1.0

    return scalef_raw * medium_ratio, spot
