"""Unified dataset import script.

Replaces the 7 organ-specific import_*.py scripts with a single CLI:

    python import_datasets.py --organ lung
    python import_datasets.py --organ breast --dry-run
    python import_datasets.py --organ kidney --dry-run

Organ configs are defined in ORGAN_CONFIGS below. To add a new organ,
add an entry to ORGAN_CONFIGS and run:

    python import_datasets.py --organ <new_organ>

Usage:
    python import_datasets.py --organ lung [--dry-run]
    python import_datasets.py --list
"""
import argparse
import json
from common import run_import


ORGAN_CONFIGS = {
    'lung': {
        'organ_name': 'Lung',
        'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/lung',
        'recursive': False,
        'default_disease': 'Normal',
        'description': '',
    },
    'liver': {
        'organ_name': 'Liver',
        'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/liver',
        'recursive': False,
        'default_disease': 'Normal',
        'description': 'Imported from Liver root dir',
    },
    'thymus': {
        'organ_name': 'Thymus',
        'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/thymus',
        'recursive': False,
        'default_disease': 'Normal',
        'description': '',
    },
    'heart': {
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
    },
    'breast': {
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
    },
    'intestine': {
        'organ_name': 'Intestine',
        'base_dir': '/data3/platform/sc_db/scgpt/data/cellxgene/st/intestine',
        'recursive': True,
        'disease_map': {'cancer': 'Cancer'},
        'root_disease': 'Normal',
        'description': '',
    },
    'kidney': {
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
    },
}


def main():
    parser = argparse.ArgumentParser(description='Import datasets into the database')
    parser.add_argument('--organ', type=str, choices=list(ORGAN_CONFIGS.keys()),
                        help='Organ to import (e.g. lung, liver, heart)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Scan and print without writing to DB')
    parser.add_argument('--list', action='store_true',
                        help='List available organ configs')
    args = parser.parse_args()

    if args.list:
        print('Available organs:')
        for name, cfg in ORGAN_CONFIGS.items():
            print(f'  {name:12s} -> {cfg["organ_name"]:12s} ({cfg.get("base_dir", "?")})')
        return

    if not args.organ:
        parser.error('--organ is required (use --list to see options)')

    config = ORGAN_CONFIGS[args.organ].copy()
    config['dry_run'] = args.dry_run
    run_import(config)


if __name__ == '__main__':
    main()
