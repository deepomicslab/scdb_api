"""Shared utilities for dataset import scripts.

All 7 organ-specific import scripts (import_lung.py, import_heart.py, etc.)
delegate to run_import() with a config dict, eliminating ~600 lines of
copy-pasted bootstrap + traversal logic.

Key improvement over the old scripts: wraps the import loop in
set_bulk_import(True) to suppress per-row refresh_global_stats() (which
made imports O(N^2)). The global stats are refreshed once at the end.
"""
import os
import sys
import django


def setup_django():
    """Bootstrap Django so Dataset model is available."""
    sys.path.append(os.getcwd())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
    django.setup()


def generate_dataset_id(organ, disease, index):
    """Generate a stable dataset ID: '{Organ}_{Disease}_{NNN}'.

    Disease names are cleaned (dashes -> underscores, capitalized) to
    match the convention used in existing data.
    """
    clean_disease = disease.replace('-', '_').capitalize()
    return f"{organ.capitalize()}_{clean_disease}_{index:03d}"


def _iter_h5ad_files_flat(base_dir, skip_files=None):
    """Yield (file_name, full_path) for .h5ad files in base_dir (non-recursive)."""
    skip_files = skip_files or set()
    if not os.path.exists(base_dir):
        print(f"  Error: path not found: {base_dir}")
        return
    all_items = sorted(os.listdir(base_dir))
    for file_name in all_items:
        full_path = os.path.join(base_dir, file_name)
        if not os.path.isfile(full_path):
            continue
        if not file_name.endswith('.h5ad'):
            continue
        if 'donor_stats' in file_name:
            continue
        if file_name in skip_files:
            print(f"  [skip-blacklist] {file_name}")
            continue
        yield file_name, full_path


def _iter_h5ad_files_recursive(base_dir, disease_map, root_disease=None,
                                skip_dirs=None, skip_files=None):
    """Yield (file_name, full_path, disease_label, folder_name) for .h5ad files.

    Args:
        base_dir: Root directory to walk.
        disease_map: {folder_name: disease_label} mapping for subdirectories.
        root_disease: Disease label for files in the root directory itself.
                  If None, root directory files are skipped (breast behavior).
        skip_dirs: Set of directory basenames to skip (e.g. {'sc'}).
        skip_files: Set of filenames to skip.
    """
    skip_dirs = skip_dirs or set()
    skip_files = skip_files or set()
    for root, dirs, files in sorted(os.walk(base_dir)):
        if os.path.basename(root) in skip_dirs:
            continue

        current_folder = os.path.basename(root)

        if root == base_dir:
            if root_disease is None:
                continue
            disease_label = root_disease
        else:
            disease_label = disease_map.get(current_folder, current_folder)

        files.sort()
        for file_name in files:
            if not file_name.endswith('.h5ad'):
                continue
            if 'donor_stats' in file_name:
                continue
            if file_name in skip_files:
                print(f"  [skip-blacklist] {file_name}")
                continue
            full_path = os.path.join(root, file_name)
            yield file_name, full_path, disease_label, current_folder


def run_import(config):
    """Run a dataset import based on a config dict.

    Required config keys:
        organ_name: str (e.g. "Lung")
        base_dir: str (path to scan)
        recursive: bool (True = os.walk, False = os.listdir)

    Optional config keys:
        default_disease: str (for flat mode, or root files in recursive mode)
        disease_map: dict {folder_name: disease_label} (recursive mode)
        root_disease: str (disease for root-level files in recursive mode;
                      None = skip root files)
        force_disease: str (override disease for all files, e.g. "Cancer")
        skip_files: set of filenames to skip
        skip_dirs: set of dir names to skip (default: {'sc'})
        description: str (description for all datasets)
        description_from_folder: bool (use f"Imported from {folder_name}")
        dry_run: bool (default False)
    """
    setup_django()
    from dataset.models import Dataset, set_bulk_import, _do_refresh_global_stats

    organ_name = config['organ_name']
    base_dir = config['base_dir']
    recursive = config.get('recursive', False)
    force_disease = config.get('force_disease')
    default_disease = config.get('default_disease', 'Normal')
    disease_map = config.get('disease_map', {})
    root_disease = config.get('root_disease')
    skip_files = config.get('skip_files', set())
    skip_dirs = config.get('skip_dirs', {'sc'})
    description = config.get('description', '')
    description_from_folder = config.get('description_from_folder', False)
    dry_run = config.get('dry_run', False)

    print(f"  Starting import: {organ_name} from {base_dir}")
    print(f"  Mode: {'recursive' if recursive else 'flat'} | Dry run: {dry_run}")

    counters = {}
    total_files = 0
    skipped_count = 0

    if not recursive:
        for file_name, full_path in _iter_h5ad_files_flat(base_dir, skip_files):
            disease_label = force_disease or default_disease
            if disease_label not in counters:
                counters[disease_label] = 1
            idx = counters[disease_label]
            ds_id = generate_dataset_id(organ_name, disease_label, idx)
            counters[disease_label] += 1
            title = file_name.replace('.h5ad', '')

            print(f"  Found: {file_name}")
            print(f"    ID: {ds_id} | Disease: {disease_label}")

            if not dry_run:
                try:
                    obj, created = Dataset.objects.update_or_create(
                        dataset_id=ds_id,
                        defaults={
                            'title': title,
                            'file_path': full_path,
                            'organ': organ_name,
                            'disease': disease_label,
                            'description': description,
                        }
                    )
                    status = "NEW" if created else "UPDATE"
                    print(f"    {status} success (Spots: {obj.n_spots})")
                except Exception as e:
                    print(f"    FAILED: {e}")
            total_files += 1
    else:
        for file_name, full_path, disease_label, folder_name in _iter_h5ad_files_recursive(
            base_dir, disease_map, root_disease, skip_dirs, skip_files
        ):
            if force_disease:
                disease_label = force_disease
            if disease_label not in counters:
                counters[disease_label] = 1
            idx = counters[disease_label]
            ds_id = generate_dataset_id(organ_name, disease_label, idx)
            counters[disease_label] += 1
            title = file_name.replace('.h5ad', '')

            desc = f"Imported from {folder_name}" if description_from_folder else description

            loc_tag = "[ROOT]" if os.path.dirname(full_path) == base_dir else f"[{folder_name}]"
            print(f"  {loc_tag} Found: {file_name}")
            print(f"    ID: {ds_id} | Disease: {disease_label}")

            if not dry_run:
                try:
                    obj, created = Dataset.objects.update_or_create(
                        dataset_id=ds_id,
                        defaults={
                            'title': title,
                            'file_path': full_path,
                            'organ': organ_name,
                            'disease': disease_label,
                            'description': desc,
                        }
                    )
                    status = "NEW" if created else "UPDATE"
                    print(f"    {status} success (Spots: {obj.n_spots})")
                except Exception as e:
                    print(f"    FAILED: {e}")
            total_files += 1

    print("=" * 40)
    print(f"  Done. Imported: {total_files} files.")

    # Refresh global stats once (not per-row)
    if not dry_run:
        print("  Refreshing global stats...")
        set_bulk_import(True)
        try:
            _do_refresh_global_stats()
        finally:
            set_bulk_import(False)
        print("  Global stats refreshed.")
    else:
        print("  (dry run - no DB writes)")
