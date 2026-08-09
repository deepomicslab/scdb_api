"""Precompute Original ST analysis results (commot/cellchat/spider/alphatalk)
on the raw ST h5ad of every Dataset, storing results under
ST_PRECOMPUTED_ROOT/{uuid}/subtask_{type}/result/st/.

These results are dataset-level (independent of any user SC input), so they are
computed once and reused by every task; the per-tool result directory is written
back into Dataset.precomputed_*_path once the SLURM job finishes.

Usage:
    python manage.py precache_st_results [--organ lung] [--dataset-id <id>...]
                                         [--tool commot] [--dry-run]
    python manage.py precache_st_results --sync
"""
import glob
import json
import os

from django.core.management.base import BaseCommand

from dataset.models import Dataset
from utils.analysis.subscstquery import SubScstquery
from utils import slurm_api
from scdb_api import settings_local as local_settings

TOOLS = {
    'commot': {
        'subtask_type': 'commot',
        'field': 'precomputed_commot_path',
        'products': ('*_LR.h5ad',),
        'params': {
            'signaling_type': 'All',
            'dis_thr': 200,
            'min_cell_pct': 0.05,
            'n_permutations': 100,
        },
    },
    'cellchat': {
        'subtask_type': 'cellchat',
        'field': 'precomputed_cellchat_path',
        'products': ('cellchat_result.rds',),
        'params': {
            'groupby': 'cell_type',
            'db_mode': 'all',
            'datatype': 'st',
            'min_cells': 10,
            'zero_dist_handle': 'none',
            'sc_type': 'triMean',
            'st_type': 'truncatedMean',
            'trim': 0.1,
            'interaction_range': 250,
        },
    },
    'spider': {
        'subtask_type': 'spider',
        'field': 'precomputed_spider_path',
        'products': ('adata_spider.h5ad',),
        'params': {
            'species': 'human',
            'datatype': 'st',
            'groupby': 'cell_type',
            'p_value': 0.05,
        },
    },
    'alphatalk': {
        'subtask_type': 'alphatalk',
        'field': 'precomputed_alphatalk_path',
        'products': ('cci_result.pkl',),
        'params': {
            'species': 'human',
        },
    },
}

JOBS_FILE = '.precompute_jobs.json'

FAILED_STATES = ('FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL', 'PREEMPTED',
                 'BOOT_FAIL', 'OUT_OF_MEMORY')


def _result_dir(dataset_uuid, subtask_type):
    return os.path.join(local_settings.ST_PRECOMPUTED_ROOT, dataset_uuid,
                        f'subtask_{subtask_type}', 'result', 'st')


def _has_products(result_dir, products):
    if not result_dir or not os.path.isdir(result_dir):
        return False
    for pattern in products:
        if not glob.glob(os.path.join(result_dir, pattern)):
            return False
    return True


def _jobs_path():
    return os.path.join(local_settings.ST_PRECOMPUTED_ROOT, JOBS_FILE)


def _load_jobs():
    try:
        with open(_jobs_path(), 'r') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_jobs(jobs):
    os.makedirs(local_settings.ST_PRECOMPUTED_ROOT, exist_ok=True)
    with open(_jobs_path(), 'w') as f:
        json.dump(jobs, f, indent=2)


class Command(BaseCommand):
    help = 'Submit (or sync) precomputed Original ST analysis jobs for all datasets'

    def add_arguments(self, parser):
        parser.add_argument('--organ', action='append', default=None,
                            help='Restrict to a dataset organ (repeatable)')
        parser.add_argument('--dataset-id', action='append', default=None,
                            help='Restrict to specific dataset_ids (repeatable)')
        parser.add_argument('--tool', action='append', default=None,
                            choices=list(TOOLS.keys()),
                            help='Restrict to specific tools (repeatable; default all)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print what would be submitted without submitting')
        parser.add_argument('--sync', action='store_true',
                            help='Check submitted jobs, update Dataset fields, do not submit')

    def handle(self, *args, **options):
        if options['sync']:
            self._sync()
            return

        tools = list(TOOLS.keys())
        if options['tool']:
            tools = [t for t in options['tool'] if t in TOOLS]

        qs = Dataset.objects.all().order_by('organ', 'title')
        if options['organ']:
            qs = qs.filter(organ__in=options['organ'])
        if options['dataset_id']:
            qs = qs.filter(dataset_id__in=options['dataset_id'])

        datasets = list(qs)
        self.stdout.write(f'Matched {len(datasets)} datasets, tools: {tools}')

        jobs = _load_jobs()
        submitted = 0
        skipped = 0
        for ds in datasets:
            for tool in tools:
                cfg = TOOLS[tool]
                if getattr(ds, cfg['field']):
                    skipped += 1
                    continue
                result_dir = _result_dir(ds.title, cfg['subtask_type'])
                if _has_products(result_dir, cfg['products']):
                    # Result already on disk but DB field not set: adopt it.
                    setattr(ds, cfg['field'], result_dir)
                    ds.save()
                    self.stdout.write(self.style.SUCCESS(
                        f'[adopt] {ds.dataset_id} {tool}: {result_dir}'))
                    continue
                if options['dry_run']:
                    self.stdout.write(f'[dry-run] {ds.dataset_id} {tool} -> {result_dir}')
                    continue
                params = {
                    'userid': 'precompute_st',
                    'input_source': 'st',
                    'sub_type': tool,
                    'projectname': 'precompute_st',
                    'organParts': '',
                }
                params.update(cfg['params'])
                try:
                    module = SubScstquery(cfg['subtask_type'], 'precompute_st',
                                          ds.title, '', ds.file_path, params)
                    job_id = module.process()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'[error] {ds.dataset_id} {tool}: {e}'))
                    continue
                jobs.setdefault(ds.title, {})[tool] = job_id
                submitted += 1
                self.stdout.write(f'[submit] {ds.dataset_id} {tool}: job {job_id}')
        _save_jobs(jobs)
        self.stdout.write(self.style.SUCCESS(
            f'Done. submitted={submitted}, skipped={skipped} (already computed)'))

    def _sync(self):
        jobs = _load_jobs()
        if not jobs:
            self.stdout.write('No pending jobs in .precompute_jobs.json')
            return
        remaining = {}
        failed = []
        for dataset_uuid, tool_jobs in jobs.items():
            ds = Dataset.objects.filter(title=dataset_uuid).first()
            for tool, job_id in tool_jobs.items():
                cfg = TOOLS[tool]
                result_dir = _result_dir(dataset_uuid, cfg['subtask_type'])
                if _has_products(result_dir, cfg['products']):
                    if ds is not None:
                        setattr(ds, cfg['field'], result_dir)
                        ds.save()
                    self.stdout.write(self.style.SUCCESS(
                        f'[completed] {dataset_uuid} {tool} (job {job_id})'))
                    continue
                status = slurm_api.get_job_status(job_id)
                normalized = slurm_api.normalize_slurm_status(status)
                if status and status.upper() in FAILED_STATES:
                    failed.append((dataset_uuid, tool, job_id, status))
                    self.stdout.write(self.style.ERROR(
                        f'[failed] {dataset_uuid} {tool} (job {job_id}): {status}'))
                    continue
                if normalized in ('Pending', 'Running'):
                    self.stdout.write(f'[active] {dataset_uuid} {tool} (job {job_id}): {status}')
                    remaining.setdefault(dataset_uuid, {})[tool] = job_id
                    continue
                # Unknown status: keep for another sync round.
                self.stdout.write(self.style.WARNING(
                    f'[unknown] {dataset_uuid} {tool} (job {job_id}): {status}'))
                remaining.setdefault(dataset_uuid, {})[tool] = job_id
        _save_jobs(remaining)
        self.stdout.write(self.style.SUCCESS(
            f'Sync done. remaining={sum(len(v) for v in remaining.values())}, '
            f'failed={len(failed)}'))
        if failed:
            self.stdout.write('Failed jobs (rerun after fixing, or inspect SLURM logs):')
            for uuid, tool, job_id, status in failed:
                self.stdout.write(f'  {uuid} {tool} job {job_id} ({status})')
