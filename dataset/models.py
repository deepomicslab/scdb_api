# dataset/models.py

import os
import anndata as ad
from django.db import models, transaction
from django.db.models import Sum, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from utils.logging import get_logger

logger = get_logger('dataset_models')

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
    # title is the h5ad file stem (directory key in the task workspace); verified
    # unique across all 224 datasets, so a unique index both speeds lookups and
    # prevents future duplicate imports.
    title = models.CharField(max_length=200, unique=True)
    file_path = models.CharField(max_length=500)

    organ = models.CharField(max_length=100)
    disease = models.CharField(max_length=100, default='Normal')
    description = models.TextField(blank=True, default='')

    n_spots = models.IntegerField(default=0, editable=False)
    n_donors = models.IntegerField(default=0, editable=False)
    donor_list = models.JSONField(default=list, editable=False)

    cell_type_counts = models.JSONField(default=dict, blank=True, editable=False)

    # Spatial calibration + images (extracted once at import/backfill; getImg and
    # scatter endpoints read them directly, no longer opening the h5ad every time)
    # image_dir: image folder relative to MEDIA_ROOT, file names follow the
    # convention thumbnail.jpg / medium.jpg / hires.jpg
    image_dir = models.CharField(max_length=300, blank=True, default='', editable=False)
    # scalef_raw: raw h5ad scalef (not multiplied by ratio); medium-space conversion
    # is computed on the fly by the reader from the actual image file dimensions
    scalef_raw = models.FloatField(null=True, blank=True, editable=False)
    spot_diameter_fullres = models.FloatField(null=True, blank=True, editable=False)

    citation_label = models.CharField(max_length=500, blank=True, default='')
    citation_url = models.CharField(max_length=500, blank=True, default='')
    collection_url = models.CharField(max_length=500, blank=True, default='')
    explorer_url = models.CharField(max_length=500, blank=True, default='')

    # Precomputed Original ST analysis result directories (per tool; non-empty
    # means that tool has been precomputed on the raw ST h5ad). Populated by the
    # precache_st_results management command and read by the mixin result
    # locators when the frontend requests input_source='st'.
    precomputed_commot_path = models.CharField(max_length=500, blank=True, default='')
    precomputed_cellchat_path = models.CharField(max_length=500, blank=True, default='')
    precomputed_spider_path = models.CharField(max_length=500, blank=True, default='')
    precomputed_alphatalk_path = models.CharField(max_length=500, blank=True, default='')

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
            logger.warning('[Dataset._extract_metadata] Failed to read %s: %s', self.file_path, e)

        # Spatial calibration (h5py reads scalars/metadata only; local import
        # avoids a circular import with utils.spatial_calibration)
        from utils.spatial_calibration import extract_spatial_calibration
        scalef_raw, spot = extract_spatial_calibration(self.file_path)
        if scalef_raw is not None or spot is not None:
            self.scalef_raw = scalef_raw
            self.spot_diameter_fullres = spot

        # Extract the 3 JPEG tiers (read directly by getImg, no longer extracted from h5ad on demand)
        self._extract_images()

    def has_image(self):
        """Whether hires.jpg is cached (thumbnail/medium can be rebuilt by getImg
        from hires; the 3 tiers read directly by getImg are generated at once by
        _extract_images in the same directory)."""
        if not self.image_dir and not self.dataset_id:
            return False
        from django.conf import settings
        image_dir = self.image_dir or f'st/{self.dataset_id}'
        return os.path.exists(os.path.join(settings.MEDIA_ROOT, image_dir, 'hires.jpg'))

    def _extract_images(self):
        """Extract the 3 JPEG tiers from h5ad into MEDIA_ROOT/{image_dir}/.

        File name convention: thumbnail.jpg / medium.jpg / hires.jpg (getImg
        concatenates them by resolution). Source image priority matches getImg
        (hires -> lowres); all 3 tiers are generated from the same source.
        """
        import h5py
        from PIL import Image
        from django.conf import settings
        from utils.spatial_calibration import IMAGE_RES_SPECS, pil_image_from_array

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
            # Single source of truth for the spec table (IMAGE_RES_SPECS): file name / max size / quality
            for filename, max_size, save_kwargs in IMAGE_RES_SPECS.values():
                copy = img.copy()
                if max_size:
                    copy.thumbnail((max_size, max_size), Image.LANCZOS)
                copy.save(os.path.join(out_dir, filename), 'JPEG', **save_kwargs)

            if not self.image_dir:
                self.image_dir = image_dir
        except Exception as e:
            logger.warning('[Dataset._extract_images] Failed for %s: %s', file_path, e)


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
