"""Import Kidney datasets. Thin wrapper around common.run_import.

Usage: python import_kidney.py [--dry-run]
Equivalent: python import_datasets.py --organ kidney
"""
from common import run_import

CONFIG = {
    'organ_name': 'Kidney',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/kidney',
    'recursive': True,
    'force_disease': 'Cancer',
    'description': '',
    'description_from_folder': True,
    'skip_files': {
        '02fba04c-c5c0-4e44-98f5-e3c5588918f8.h5ad',
        'cbeaecd5-8aeb-4cf0-8a3c-4164c9d62493.h5ad',
    },
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
