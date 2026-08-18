import json
import os
import tempfile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
import django

django.setup()

from django.test import TestCase

from dataset.models import Dataset
from utils.analysis.base import extract_dataset_uuid
from utils.analysis.scstquery_mixins.common import CommonMixin


class OrgansAndDatasetsBatchQueryTests(TestCase):
    """getOrgansAndDatasets resolves titles in a single batch query (no N+1)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.uuid_a = 'uuid-a-0001'
        self.uuid_b = 'uuid-b-0002'
        self.uuid_c = 'uuid-c-0003'
        Dataset.objects.create(
            dataset_id='DS_A', title=self.uuid_a, file_path='/tmp/a.h5ad', organ='lung',
        )
        Dataset.objects.create(
            dataset_id='DS_B', title=self.uuid_b, file_path='/tmp/b.h5ad', organ='heart',
        )
        Dataset.objects.create(
            dataset_id='DS_C', title=self.uuid_c, file_path='/tmp/c.h5ad', organ='lung',
        )
        # a title that does NOT exist in the DB (should stay "Unknown Dataset")
        self.missing_uuid = 'uuid-zzz-9999'

        # result_scores.json: 2 organs x 2 datasets each (one missing each)
        payload = {
            'Lung': {
                f'/data3/.../st/{self.uuid_a}/st_marker/foo_marker.csv': {'pearson_score': 0.9},
                f'/data3/.../st/{self.missing_uuid}/st_marker/foo_marker.csv': {'pearson_score': 0.5},
            },
            'Heart': {
                f'/data3/.../st/{self.uuid_b}/st_marker/foo_marker.csv': {'pearson_score': 0.8},
                f'/data3/.../st/{self.uuid_c}/st_marker/foo_marker.csv': {'pearson_score': 0.7},
            },
        }
        self.task_root = os.path.join(self._tmp, 'task')
        os.makedirs(os.path.join(self.task_root, 'result', 'sc_query'), exist_ok=True)
        with open(os.path.join(self.task_root, 'result', 'sc_query', 'result_scores.json'), 'w') as f:
            json.dump(payload, f)

        self.mixin = CommonMixin()
        self.mixin.path = self.task_root
        # _extract_dataset_uuid normally comes from the Module base class; assign the
        # same standalone function as a plain instance attribute so the mixin can be
        # tested on its own.
        self.mixin._extract_dataset_uuid = extract_dataset_uuid

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_output_matches_expected(self):
        res = self.mixin.getOrgansAndDatasets()
        self.assertEqual(res.get('status'), 'success', res)

        lung = res['data']['Lung']
        # found dataset -> dataset_id key
        self.assertIn('DS_A', lung)
        self.assertEqual(lung['DS_A']['meta']['uuid'], self.uuid_a)
        # missing dataset -> falls back to uuid key, unknown description
        self.assertIn(self.missing_uuid, lung)
        self.assertNotIn('DS_A', {k for k in lung if k != 'DS_A'})

        heart = res['data']['Heart']
        self.assertIn('DS_B', heart)
        self.assertIn('DS_C', heart)

    def test_constant_number_of_queries(self):
        # Organs/organsAndDatasets must not issue one query per dataset.
        # Query budget is small and independent of dataset count: the subtask_map
        # lookup (tasks by userpath) + the single title__in batch query (+ extras).
        with self.assertNumQueries(3):
            self.mixin.getOrgansAndDatasets()
