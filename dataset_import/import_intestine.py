"""Import Intestine datasets. Thin wrapper around common.run_import.

Usage: python import_intestine.py [--dry-run]
Equivalent: python import_datasets.py --organ intestine
"""
from common import run_import

CONFIG = {
    'organ_name': 'Intestine',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/intestine',
    'recursive': True,
    'disease_map': {'cancer': 'Cancer'},
    'root_disease': 'Normal',
    'description': '',
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
