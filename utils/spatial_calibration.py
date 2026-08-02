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


def extract_spatial_calibration(file_path):
    """从 h5ad 提取空间校准的原始值：scalef_raw、源图尺寸、spot 直径。

    返回 (scalef_raw, spot, img_w, img_h)：
      - scalef_raw: 未乘 medium_ratio 的原始 scalef（hires→lowres 优先级解析后）
      - img_w/img_h: 该源的图像尺寸（medium_ratio = min(800/w, 800/h) 读取时计算）
      - spot: spot_diameter_fullres

    与 getImg 的图像源优先级一致（hires → lowres），保证 scalef 匹配实际被服务的图。
    """
    if not file_path or not os.path.exists(file_path):
        return None, None, None, None

    scalef = None
    spot = None
    img_w = None
    img_h = None
    try:
        with h5py.File(file_path, 'r') as f:
            uns_spatial = f.get('uns/spatial')
            if uns_spatial is None:
                return scalef, spot, img_w, img_h
            libs = list(uns_spatial.keys())
            if not libs:
                return scalef, spot, img_w, img_h

            lib = libs[0]

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

                try:
                    arr = f[img_path]
                    img_h, img_w = arr.shape[0], arr.shape[1]
                except Exception:
                    pass

                break  # First found image wins (hires -> lowres priority)

    except Exception as e:
        print(f'[extract_spatial_calibration] error for {file_path}: {e}')

    return scalef, spot, img_w, img_h


def read_spatial_calibration(dataset_id):
    """Read (tissue_hires_scalef, spot_diameter_fullres) for a dataset.

    DB-first: scalef_raw/image_w/image_h/spot_diameter_fullres 由导入/backfill 时
    提取入库，这里直接读库并计算 medium 空间 scalef（一次乘法，避免每次开 h5ad）。

    字段缺失（迁移前数据/新导入未 backfill）时自愈：从 h5ad 提取并写回数据库。

    返回的 scalef 已调整到 medium 分辨率空间（MEDIUM_MAX_SIZE px，与 getImg 默认档一致）。
    """
    if not dataset_id:
        return None, None
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
    except Dataset.DoesNotExist:
        return None, None

    scalef_raw = ds.scalef_raw
    spot = ds.spot_diameter_fullres
    img_w = ds.image_w
    img_h = ds.image_h

    if scalef_raw is None or not img_w or not img_h:
        # 自愈：字段缺失 → 从 h5ad 提取并写回
        scalef_raw, spot, img_w, img_h = extract_spatial_calibration(ds.file_path)
        if scalef_raw is None or not img_w or not img_h:
            return scalef_raw, spot
        Dataset.objects.filter(dataset_id=dataset_id).update(
            scalef_raw=scalef_raw,
            spot_diameter_fullres=spot,
            image_w=img_w,
            image_h=img_h,
        )

    medium_ratio = min(MEDIUM_MAX_SIZE / img_w, MEDIUM_MAX_SIZE / img_h)
    return scalef_raw * medium_ratio, spot
