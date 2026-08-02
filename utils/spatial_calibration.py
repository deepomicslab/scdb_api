import os
import h5py
from PIL import Image
from django.conf import settings
from dataset.models import Dataset


# 图片分辨率常量（可随时调整：getImg 校验到实际文件不符时自动按新值重建）
MEDIUM_MAX_SIZE = 800
THUMBNAIL_MAX_SIZE = 400

# 图片规格表（单一来源）：resolution -> (文件名, 最大尺寸, 保存参数)
# 供 getImg 与 Dataset._extract_images 共用；max_size=None 表示原尺寸（hires）
IMAGE_RES_SPECS = {
    'thumbnail': ('thumbnail.jpg', THUMBNAIL_MAX_SIZE, {'quality': 75, 'optimize': True}),
    'medium': ('medium.jpg', MEDIUM_MAX_SIZE, {'quality': 80, 'optimize': True}),
    'original': ('hires.jpg', None, {'quality': 85, 'optimize': True}),
}


def pil_image_from_array(arr):
    """h5ad 图像数组 → JPEG 可写的 PIL Image。

    JPEG 不支持 RGBA/带 alpha 的模式：透明图先合成到白底，其它非常规模式转 RGB。
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
    """从 h5ad 提取空间校准的原始值。

    返回 (scalef_raw, spot)：
      - scalef_raw: 未乘任何 ratio 的原始 scalef（hires→lowres 优先级解析后）
      - spot: spot_diameter_fullres

    与 getImg 的图像源优先级一致（hires → lowres），保证 scalef 匹配实际被服务的图。
    medium 空间换算由 read_spatial_calibration 按实际文件尺寸实时计算（方案 B）。
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

            # 库选择：跳过标量标志位（如 is_single），取第一个含 images/scalefactors 的 Group
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
    """读 JPEG 头部尺寸（不解码像素），失败返回 (None, None)。"""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def read_spatial_calibration(dataset_id):
    """Read (tissue_hires_scalef, spot_diameter_fullres) for a dataset.

    DB-first: scalef_raw/spot_diameter_fullres 由导入/backfill 时提取入库。
    medium 空间换算（方案 B）：ratio 按实际服务的 medium.jpg / hires.jpg 真实尺寸
    计算（ratio = medium_w / hires_w），与 getImg 实际下发的图永远一致——
    MEDIUM_MAX_SIZE 常量随时可变，图重建后 ratio 自动跟上，无错位窗口期。

    字段缺失（迁移前数据/新导入未 backfill）时自愈：从 h5ad 提取并写回数据库。
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
        # 自愈：字段缺失 → 从 h5ad 提取并写回
        scalef_raw, spot = extract_spatial_calibration(ds.file_path)
        if scalef_raw is None:
            return None, None
        Dataset.objects.filter(dataset_id=dataset_id).update(
            scalef_raw=scalef_raw,
            spot_diameter_fullres=spot,
        )

    # ratio 按实际文件尺寸（方案 B）；文件缺失时按 hires 实际长边 + 常量兜底
    medium_path = os.path.join(settings.MEDIA_ROOT, ds.image_dir, 'medium.jpg')
    hires_path = os.path.join(settings.MEDIA_ROOT, ds.image_dir, 'hires.jpg')
    mw, _mh = _jpeg_dimensions(medium_path)
    hw, hh = _jpeg_dimensions(hires_path)
    if mw and hw:
        medium_ratio = mw / hw
    elif hw and hh:
        # 兜底：medium.jpg 缺失时按 hires 实际长边 + 常量估算
        medium_ratio = min(MEDIUM_MAX_SIZE / hw, MEDIUM_MAX_SIZE / hh)
    else:
        medium_ratio = 1.0

    return scalef_raw * medium_ratio, spot
