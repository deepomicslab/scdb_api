"""Import Breast datasets. Thin wrapper around common.run_import.

Usage: python import_breast.py [--dry-run]
Equivalent: python import_datasets.py --organ breast
"""
from common import run_import

CONFIG = {
    'organ_name': 'Breast',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/breast',
    'recursive': True,
    'disease_map': {
        'cancer': 'Cancer',
        'GSE195665': 'Normal',
        'GSE213688': 'Normal',
    },
    'root_disease': None,
    'description': '',
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
