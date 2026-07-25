"""Import Lung datasets. Thin wrapper around common.run_import.

Usage: python import_lung.py [--dry-run]
Equivalent: python import_datasets.py --organ lung
"""
from common import run_import

CONFIG = {
    'organ_name': 'Lung',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/lung',
    'recursive': False,
    'default_disease': 'Normal',
    'description': '',
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
