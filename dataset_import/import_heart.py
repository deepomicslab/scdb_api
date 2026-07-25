"""Import Heart datasets. Thin wrapper around common.run_import.

Usage: python import_heart.py [--dry-run]
Equivalent: python import_datasets.py --organ heart
"""
from common import run_import

CONFIG = {
    'organ_name': 'Heart',
    'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/heart',
    'recursive': False,
    'default_disease': 'Normal',
    'description': 'Imported from Heart root dir only',
    'skip_files': {
        '10a8514a-f843-4d81-835b-18de32b1f8a3.h5ad',
        '31c4fea3-8f50-44ad-b012-fc8274b30bf3.h5ad',
        '366b22f0-58e7-47d3-824f-e88c6fb28f6b.h5ad',
        '42c47fef-56e5-4133-9201-e2254bdc15e5.h5ad',
        '4c861bfb-8276-49d7-8b64-6d905a8b887a.h5ad',
        '4dfc0978-303f-4550-8dcd-0f084f4ea089.h5ad',
        '6a802eb8-81f1-4904-9474-0ff315850d72.h5ad',
        'b2df9cc2-2c45-4d3e-9334-273d13035dc3.h5ad',
        'fbed512d-5a63-434a-80fb-356bb6e9987e.h5ad',
    },
}

if __name__ == '__main__':
    import sys
    CONFIG['dry_run'] = '--dry-run' in sys.argv
    run_import(CONFIG)
