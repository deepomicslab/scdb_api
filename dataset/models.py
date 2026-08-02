# dataset/models.py

import os
import anndata as ad
from django.db import models, transaction
from django.db.models import Sum, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

CELL_TYPE_COL = 'cell_type'

# Module-level flag to skip per-row signal during bulk imports
_BULK_IMPORT = False


def set_bulk_import(enabled):
    """Enable/disable bulk import mode.
    When enabled, refresh_global_stats signal is skipped.
    Caller must manually call refresh_global_stats() after bulk import.
    """
    global _BULK_IMPORT
    _BULK_IMPORT = enabled


# === 1. Global stats table (single row, ID=1) ===
class GlobalStat(models.Model):
    total_spots = models.BigIntegerField(default=0)
    total_donors = models.IntegerField(default=0)
    total_organs = models.IntegerField(default=0)
    total_datasets = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GlobalStat (updated: {self.updated_at})"


# === 2. Dataset table ===
class Dataset(models.Model):
    dataset_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=200)
    file_path = models.CharField(max_length=500)

    organ = models.CharField(max_length=100)
    disease = models.CharField(max_length=100, default='Normal')
    description = models.TextField(blank=True, default='')

    n_spots = models.IntegerField(default=0, editable=False)
    n_donors = models.IntegerField(default=0, editable=False)
    donor_list = models.JSONField(default=list, editable=False)

    cell_type_counts = models.JSONField(default=dict, blank=True, editable=False)

    # 空间校准 + 图片（导入/backfill 时提取一次，getImg 与散点接口直读，不再每次开 h5ad）
    # image_dir: 相对 MEDIA_ROOT 的图片文件夹，文件名按约定 thumbnail.jpg / medium.jpg / hires.jpg
    image_dir = models.CharField(max_length=300, blank=True, default='', editable=False)
    # scalef_raw: h5ad 原始 scalef（未乘 medium_ratio）；读取时按 image_w/h 计算 medium 空间值
    scalef_raw = models.FloatField(null=True, blank=True, editable=False)
    image_w = models.IntegerField(null=True, blank=True, editable=False)
    image_h = models.IntegerField(null=True, blank=True, editable=False)
    spot_diameter_fullres = models.FloatField(null=True, blank=True, editable=False)

    citation_label = models.CharField(max_length=500, blank=True, default='')
    citation_url = models.CharField(max_length=500, blank=True, default='')
    collection_url = models.CharField(max_length=500, blank=True, default='')
    explorer_url = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['organ'], name='idx_dataset_organ'),
        ]

    def save(self, *args, update_metadata=False, **kwargs):
        """Save the dataset. By default does NOT read the h5ad file.
        Pass update_metadata=True to extract n_spots/donors/cell_type_counts from h5ad.
        """
        if update_metadata and os.path.exists(self.file_path):
            self._extract_metadata()
        super().save(*args, **kwargs)

    def _extract_metadata(self):
        """Extract n_spots, donor_list, cell_type_counts from h5ad file.
        Uses backed mode with context manager to prevent file handle leaks.
        """
        try:
            with ad.read_h5ad(self.file_path, backed='r') as adata:
                self.n_spots = adata.n_obs

                obs_keys = adata.obs.keys()
                if 'donor_id' in obs_keys:
                    donors = adata.obs['donor_id'].unique().tolist()
                    self.donor_list = [str(d) for d in donors]
                    self.n_donors = len(self.donor_list)

                if CELL_TYPE_COL in obs_keys:
                    counts = adata.obs[CELL_TYPE_COL].value_counts().to_dict()
                    self.cell_type_counts = {str(k): int(v) for k, v in counts.items()}
        except Exception as e:
            print(f"[Dataset._extract_metadata] Failed to read {self.file_path}: {e}")

        # 空间校准（h5py 只读标量/元数据；局部导入避免与 utils.spatial_calibration 循环引用）
        from utils.spatial_calibration import extract_spatial_calibration
        scalef_raw, spot, img_w, img_h = extract_spatial_calibration(self.file_path)
        if scalef_raw is not None or spot is not None:
            self.scalef_raw = scalef_raw
            self.spot_diameter_fullres = spot
            self.image_w = img_w
            self.image_h = img_h

        # 提图 3 档 JPEG（getImg 直读，不再按需从 h5ad 提取）
        self._extract_images()

    def _extract_images(self):
        """从 h5ad 提取 3 档 JPEG 到 MEDIA_ROOT/{image_dir}/。

        文件名约定：thumbnail.jpg / medium.jpg / hires.jpg（getImg 按 resolution 拼接）。
        源图优先级与 getImg 一致（hires → lowres），3 档均由同一源生成。
        """
        import h5py
        from PIL import Image
        from django.conf import settings
        from utils.spatial_calibration import MEDIUM_MAX_SIZE, pil_image_from_array

        file_path = self.file_path
        if not file_path or not os.path.exists(file_path):
            return

        image_dir = self.image_dir or f'st/{self.dataset_id}'
        try:
            source = None
            with h5py.File(file_path, 'r') as f:
                if "uns/spatial" not in f:
                    return
                for lib in f["uns/spatial"].keys():
                    for img_key in ("hires", "lowres"):
                        img_full = f"uns/spatial/{lib}/images/{img_key}"
                        if img_full in f:
                            source = f[img_full][:]
                            break
                    if source is not None:
                        break
            if source is None:
                return

            out_dir = os.path.join(settings.MEDIA_ROOT, image_dir)
            os.makedirs(out_dir, exist_ok=True)

            img = pil_image_from_array(source)
            specs = [
                ('thumbnail.jpg', 400, 75),
                ('medium.jpg', MEDIUM_MAX_SIZE, 80),
                ('hires.jpg', None, 85),
            ]
            for filename, max_size, quality in specs:
                copy = img.copy()
                if max_size:
                    copy.thumbnail((max_size, max_size), Image.LANCZOS)
                copy.save(os.path.join(out_dir, filename), 'JPEG', quality=quality, optimize=True)

            if not self.image_dir:
                self.image_dir = image_dir
        except Exception as e:
            print(f"[Dataset._extract_images] Failed for {file_path}: {e}")


# === 3. Signal: auto-refresh global stats on Dataset save/delete ===
@receiver([post_save, post_delete], sender=Dataset)
def refresh_global_stats(sender, **kwargs):
    if _BULK_IMPORT:
        return
    _do_refresh_global_stats()


def _do_refresh_global_stats():
    aggs = Dataset.objects.aggregate(
        sum_spots=Sum('n_spots'),
        count_datasets=Count('id'),
        count_organs=Count('organ', distinct=True)
    )

    all_rows = Dataset.objects.values_list('donor_list', flat=True)
    unique_donors = set()
    for d_list in all_rows:
        if d_list:
            unique_donors.update(d_list)

    with transaction.atomic():
        stat_obj = GlobalStat.objects.select_for_update().get_or_create(id=1)[0]
        stat_obj.total_spots = aggs['sum_spots'] or 0
        stat_obj.total_datasets = aggs['count_datasets'] or 0
        stat_obj.total_organs = aggs['count_organs'] or 0
        stat_obj.total_donors = len(unique_donors)
        stat_obj.save()
