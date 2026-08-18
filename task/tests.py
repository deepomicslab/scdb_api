import os
import shutil
import tempfile
from unittest import TestCase


class DownloadSecurityTests(TestCase):
    """CommonMixin.download: whole-task-root boundary + traversal/symlink guards."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()
        from utils.analysis.scstquery_mixins.common import CommonMixin

        cls.CommonMixin = CommonMixin

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.task_root = os.path.join(self._tmp, 'task')
        # mixin methods only need self.path
        self.mixin = self.CommonMixin()
        self.mixin.path = self.task_root
        self._make_file('result/sc_marker', 'X_marker.csv', b'csv-content')
        self._make_file('result/sc_query/annotation_h5ad', 'ann.h5ad', b'h5ad-bytes')
        self._make_file('result/meta', 'meta.txt', b'txt-content')
        self._make_file('dataset_abc/subtask_cellchat/result', 'out.rds', b'rds-bytes')
        self._make_file('', 'taskdetail.json', b'{"modulename":"Scstquery"}')
        self._make_file('', 'moduleobject.pkl', b'pickle')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_file(self, rel_dir, name, content):
        d = os.path.join(self.task_root, rel_dir)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), 'wb') as f:
            f.write(content)

    def _download(self, filename):
        return self.mixin.download(filename)

    def _assert_success(self, res, expect_bytes):
        self.assertEqual(res.get('status'), 'success', res)
        self.assertIn('file_content', res)
        import base64
        self.assertEqual(base64.b64decode(res['file_content']), expect_bytes)

    def test_bare_csv_in_legacy_dir(self):
        self._assert_success(self._download('X_marker.csv'), b'csv-content')

    def test_bare_h5ad_in_legacy_dir(self):
        self._assert_success(self._download('ann.h5ad'), b'h5ad-bytes')

    def test_bare_txt_in_legacy_dir(self):
        self._assert_success(self._download('meta.txt'), b'txt-content')

    def test_relative_path_into_subtask_result(self):
        self._assert_success(
            self._download('dataset_abc/subtask_cellchat/result/out.rds'), b'rds-bytes'
        )

    def test_explicit_legacy_dir_relative_path(self):
        self._assert_success(self._download('result/sc_marker/X_marker.csv'), b'csv-content')

    def test_traversal_rejected(self):
        for bad in ('../task/taskdetail.json', 'a/../../etc/passwd', '..%2f..%2fetc'):
            res = self._download(bad)
            self.assertNotEqual(res.get('status'), 'success', bad)

    def test_absolute_path_rejected(self):
        res = self._download('/etc/passwd')
        self.assertNotEqual(res.get('status'), 'success')

    def test_leading_slash_rejected(self):
        res = self._download('/task/result/meta/meta.txt')
        self.assertNotEqual(res.get('status'), 'success')

    def test_empty_and_dot_segments_rejected(self):
        for bad in ('', 'result//meta/meta.txt', './meta.txt', '..', '.'):
            res = self._download(bad)
            self.assertNotEqual(res.get('status'), 'success', bad)

    def test_internal_metadata_excluded(self):
        for bad in ('taskdetail.json', 'moduleobject.pkl'):
            res = self._download(bad)
            self.assertNotEqual(res.get('status'), 'success', bad)

    def test_symlink_escape_rejected(self):
        outside = os.path.join(self._tmp, 'outside.txt')
        with open(outside, 'wb') as f:
            f.write(b'outside')
        link = os.path.join(self.task_root, 'result', 'sc_marker', 'escape.csv')
        os.symlink(outside, link)
        res = self._download('escape.csv')
        self.assertNotEqual(res.get('status'), 'success')

    def test_missing_file_fails_cleanly(self):
        res = self._download('no_such.csv')
        self.assertEqual(res.get('status'), 'fail')

    def test_extensionless_file_without_unboundlocal(self):
        # a bare unknown name must fail with a message, never raise UnboundLocalError
        res = self._download('random_file_without_extension')
        self.assertEqual(res.get('status'), 'fail')


class UploadValidationTests(TestCase):
    """createtask upload guards: HDF5 magic-byte detection."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()
        from task import views

        cls._is_h5ad_content = staticmethod(views._is_h5ad_content)

    def _write_bytes(self, data):
        import io

        f = io.BytesIO(data)
        return f

    def test_valid_hdf5_magic_accepted(self):
        f = self._write_bytes(b'\x89HDF\r\n\x1a\n' + b'rest-of-file')
        self.assertTrue(self._is_h5ad_content(f))

    def test_plain_text_rejected(self):
        f = self._write_bytes(b'this is just text, not h5ad')
        self.assertFalse(self._is_h5ad_content(f))

    def test_empty_file_rejected(self):
        f = self._write_bytes(b'')
        self.assertFalse(self._is_h5ad_content(f))

    def test_short_header_rejected(self):
        f = self._write_bytes(b'\x89HDF\r\n\x1a')  # 7 bytes, one short
        self.assertFalse(self._is_h5ad_content(f))


class CreateSubtaskAtomicityTests(TestCase):
    """create_subtask: transaction rollback + scancel of submitted jobs on failure."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def setUp(self):
        from task.models import tasks as task_model

        self.main_task = task_model.objects.create(
            name='t', user='u', userpath='u12345_0001',
            task_type='module', status='Created', modulelist='Scstquery',
        )

    def tearDown(self):
        from task.models import tasks as task_model

        task_model.objects.filter(id=self.main_task.id).delete()

    def test_failed_main_sbatch_rolls_back(self):
        """If the main subtask sbatch fails, the subtask row must not survive."""
        from unittest import mock

        import task.services as services
        from task.models import SubTask

        class FailingModule:
            def __init__(self, *a, **k):
                pass

            def process(self):
                raise RuntimeError('sbatch boom')

        with mock.patch.object(services, 'MODULE_REGISTRY',
                               {'SubScstquery': FailingModule}):
            with self.assertRaises(RuntimeError):
                services.create_subtask(
                    self.main_task, 'u', 'DS_X', 'scst_mapping', {}
                )

        self.assertEqual(SubTask.objects.filter(main_task=self.main_task).count(), 0)

    def test_prereq_submitted_then_main_fails_cancels_prereq_and_rolls_back(self):
        """umap_embedding chains scgpt_embedding: prereq job is submitted, then the
        main sbatch fails -> the prereq job must be scanceled and all rows rolled back."""
        from unittest import mock

        import task.services as services
        from task.models import SubTask

        cancelled = []

        class FailingMain:
            def __init__(self, *a, **k):
                pass

            def process(self):
                raise RuntimeError('main sbatch boom')

        def fake_chain(cls, *a, **k):
            prereq_row = SubTask.objects.create(
                main_task=self.main_task,
                subtask_type='scgpt_embedding',
                dataset_path='DS_X',
                status='Running',
                job_id='101',
            )
            return (FailingMain(), '101', prereq_row)

        with mock.patch.object(services, 'cancel_job', side_effect=lambda jid: cancelled.append(jid)), \
                mock.patch.object(services, '_chain_prerequisite', side_effect=fake_chain), \
                mock.patch.object(services, 'MODULE_REGISTRY',
                                  {'SubScstquery': FailingMain}):
            with self.assertRaises(RuntimeError):
                services.create_subtask(
                    self.main_task, 'u', 'DS_X', 'umap_embedding', {}
                )

        # every row created in this attempt rolled back
        self.assertEqual(SubTask.objects.filter(main_task=self.main_task).count(), 0)
        # the already-submitted prereq SLURM job was cancelled
        self.assertEqual(cancelled, ['101'])
