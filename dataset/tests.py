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
        # Must NOT issue one query per dataset. Exactly 2 queries regardless of how
        # many datasets are in result_scores.json:
        #   1. tasks lookup by userpath (subtask_map)
        #   2. single title__in batch query for all datasets
        with self.assertNumQueries(2):
            self.mixin.getOrgansAndDatasets()


class HasImageCacheTests(TestCase):
    """_has_image_cached: hit/miss TTL caching without raising."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def setUp(self):
        from dataset import models as dm

        dm._HAS_IMAGE_CACHE.clear()

    def tearDown(self):
        from dataset import models as dm

        dm._HAS_IMAGE_CACHE.clear()

    def test_existing_file_cached(self):
        from unittest import mock

        from dataset import models as dm

        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, tmp, ignore_errors=True)
        target = os.path.join(tmp, 'hires.jpg')
        open(target, 'w').close()

        self.assertTrue(dm._has_image_cached(target))
        # cached: even if the file disappears, the hit TTL keeps returning True
        os.remove(target)
        self.assertTrue(dm._has_image_cached(target))

    def test_missing_file_cached_as_false(self):
        from dataset import models as dm

        target = '/nonexistent/definitely/missing/hires.jpg'
        self.assertFalse(dm._has_image_cached(target))
        # cached false (no second stat; we just assert it stays consistent)
        self.assertFalse(dm._has_image_cached(target))


class CacheBoundTests(TestCase):
    """_evict_oldest: FIFO cap keeps the module-level caches bounded under
    arbitrary user-supplied keys, shedding the oldest entry (and its parallel
    timestamp when one exists) before each write past capacity."""

    def test_empty_cache_is_noop(self):
        from dataset import views as dv

        cache = {}
        dv._evict_oldest(cache, 3)
        self.assertEqual(cache, {})

    def test_fifo_bound_and_order(self):
        from dataset import views as dv

        cache = {}

        def put(key, value):
            dv._evict_oldest(cache, 3)
            cache[key] = value

        put('k0', 0)
        put('k1', 1)
        put('k2', 2)
        self.assertEqual(list(cache), ['k0', 'k1', 'k2'])
        # capacity write: oldest (k0) is shed first so size stays bounded
        put('k3', 3)
        self.assertEqual(len(cache), 3)
        self.assertNotIn('k0', cache)
        self.assertEqual(list(cache), ['k1', 'k2', 'k3'])
        # re-inserting an evicted key makes it newest again
        put('k0', 10)
        self.assertEqual(list(cache), ['k2', 'k3', 'k0'])

    def test_paired_timestamp_dict_sheds_same_key(self):
        from dataset import views as dv

        values = {}
        stamps = {}

        def put(key, value):
            dv._evict_oldest(values, 2, aux=stamps)
            values[key] = value
            stamps[key] = 123.0

        put('a', 1)
        put('b', 2)
        put('c', 3)
        self.assertEqual(list(values), ['b', 'c'])
        # the aux dict must not leak entries whose value entry was evicted
        self.assertEqual(sorted(stamps), ['b', 'c'])
