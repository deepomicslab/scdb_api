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

    citation_label = models.CharField(max_length=500, blank=True, default='')
    citation_url = models.CharField(max_length=500, blank=True, default='')
    collection_url = models.CharField(max_length=500, blank=True, default='')
    explorer_url = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

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
