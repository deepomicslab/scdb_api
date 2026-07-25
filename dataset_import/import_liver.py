"""Import Liver datasets. Thin wrapper around common.run_import.

Usage: python import_liver.py [--dry-run]
Equivalent: python import_datasets.py --organ liver
"""
from common import run_import

CONFIG = {
    'organ_name': 'Liver',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/liver',
    'recursive': False,
    'default_disease': 'Normal',
    'description': 'Imported from Liver root dir',
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
