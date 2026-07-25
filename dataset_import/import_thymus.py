"""Import Thymus datasets. Thin wrapper around common.run_import.

Usage: python import_thymus.py [--dry-run]
Equivalent: python import_datasets.py --organ thymus
"""
from common import run_import

CONFIG = {
    'organ_name': 'Thymus',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/thymus',
    'recursive': False,
    'default_disease': 'Normal',
    'description': '',
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
