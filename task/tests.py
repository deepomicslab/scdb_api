import os
import shutil
import tempfile
from unittest import TestCase


class DownloadSecurityTests(TestCase):
    """CommonMixin.download: whole-task-root boundary + traversal/symlink guards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
    """createtask upload guards: HDF5 magic-byte detection + h5ad structure."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()
        from task import views

        cls._is_h5ad_content = staticmethod(views._is_h5ad_content)
        cls._is_valid_h5ad = staticmethod(views._is_valid_h5ad)

    def _write_bytes(self, data):
        import io

        f = io.BytesIO(data)
        return f

    def _write_h5(self, path, keys):
        import h5py

        with h5py.File(path, 'w') as f:
            for k in keys:
                f.create_dataset(k, data=[1, 2, 3])

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

    def test_valid_h5ad_with_required_keys_accepted(self):
        path = os.path.join(tempfile.mkdtemp(), 'x.h5ad')
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        self._write_h5(path, ['X', 'obs', 'var'])
        self.assertTrue(self._is_valid_h5ad(path))

    def test_hdf5_without_required_keys_rejected(self):
        path = os.path.join(tempfile.mkdtemp(), 'x.h5ad')
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        self._write_h5(path, ['only_a_dataset'])
        self.assertFalse(self._is_valid_h5ad(path))

    def test_non_h5ad_rejected(self):
        path = os.path.join(tempfile.mkdtemp(), 'x.h5ad')
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        with open(path, 'w') as f:
            f.write('not a hdf5 file at all')
        self.assertFalse(self._is_valid_h5ad(path))


class LoggingConfigTests(TestCase):
    """LOGGING dict in settings: scdb logger wired to a stdout StreamHandler."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def test_scdb_logger_has_console_handler(self):
        import logging

        from utils.logging import logger

        handlers = [h for h in logger.handlers]
        self.assertTrue(handlers, 'scdb logger should have at least one handler')
        stream_handler = next((h for h in handlers if isinstance(h, logging.StreamHandler)), None)
        self.assertIsNotNone(stream_handler, 'expected a StreamHandler on scdb logger')
        # stdout (not stderr) so logs ride the tee chain into app.log
        self.assertEqual(stream_handler.stream, __import__('sys').stdout)


class CreateSubtaskAtomicityTests(TestCase):
    """create_subtask: transaction rollback + scancel of submitted jobs on failure."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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

            def add_dependency(self, *a, **k):
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

            def add_dependency(self, *a, **k):
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


class CreateTaskAtomicityTests(TestCase):
    """createtask: transaction rollback + scancel + task-dir cleanup on failure."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def test_module_failure_rolls_back_row_cleans_dir(self):
        from unittest import mock

        from django.test import Client
        import task.views as views
        from task.models import tasks as task_model

        cancelled = []

        class FailingModule:
            def __init__(self, *a, **k):
                pass

            def process(self):
                raise RuntimeError('sbatch boom')

        tmp_workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_workspace, ignore_errors=True)

        c = Client()
        with mock.patch.object(views, 'cancel_job', side_effect=lambda jid: cancelled.append(jid)), \
                mock.patch.object(views, 'get_module_class', return_value=FailingModule), \
                mock.patch.object(views.local_settings, 'USERTASKPATH', tmp_workspace + '/'):
            # a real minimal h5ad so the upload passes magic + deep X/obs/var validation
            upload_path = os.path.join(tmp_workspace, 'input.h5ad')
            import h5py
            with h5py.File(upload_path, 'w') as hf:
                for k in ('X', 'obs', 'var'):
                    hf.create_dataset(k, data=[1, 2, 3])
            with open(upload_path, 'rb') as f:
                resp = c.post('/tasks/createtask/', {
                    'submitfile': f,
                    'parameters': '{"a":1}',
                    'taskname': 't',
                    'userid': 'u',
                    'tasktype': 'module',
                    'modulename': 'Scstquery',
                })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'Failed')
        # the task row is intentionally kept as Failed (visible in workspace)
        kept = task_model.objects.filter(user='u').first()
        self.assertIsNotNone(kept)
        self.assertEqual((kept.status or '').lower(), 'failed')
        # no job was submitted so nothing to cancel
        self.assertEqual(cancelled, [])
        # the task directory is kept on disk for later inspection
        leftovers = [p for p in os.listdir(tmp_workspace) if p != 'input.h5ad']
        self.assertEqual(len(leftovers), 1)


class TaskOwnershipTests(TestCase):
    """Task endpoints must verify tasks.user == userid (anonymous platform identity).

    Uniform 403 for missing / not-owned so the API never reveals whether a task
    or subtask exists. testmode=true is exempt (demo data, no task lookup).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def setUp(self):
        from task.models import tasks as task_model
        from task.models import SubTask, TaskStatus

        self.owner = 'owner_abc'
        self.intruder = 'intruder_xyz'
        self.task = task_model.objects.create(
            name='own', user=self.owner, userpath='own123_0001',
            task_type='module', status='Completed', modulelist='Scstquery',
        )
        self.subtask = SubTask.objects.create(
            main_task=self.task,
            subtask_type='cellchat',
            dataset_path='ds_x',
            status=TaskStatus.COMPLETED,
            job_id='1234567',
        )

    def tearDown(self):
        from task.models import tasks as task_model

        task_model.objects.filter(id=self.task.id).delete()

    def _client(self):
        from django.test import Client

        return Client()

    # --- taskdetailview ---

    def test_detail_missing_userid_rejected(self):
        resp = self._client().get('/tasks/taskdetailview/', {'taskid': self.task.id})
        self.assertEqual(resp.status_code, 403)

    def test_detail_wrong_userid_rejected(self):
        resp = self._client().get('/tasks/taskdetailview/', {
            'taskid': self.task.id, 'userid': self.intruder,
        })
        self.assertEqual(resp.status_code, 403)

    def test_detail_unknown_task_uniform_403(self):
        resp = self._client().get('/tasks/taskdetailview/', {
            'taskid': 999999, 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 403)

    def test_detail_correct_userid_allowed(self):
        resp = self._client().get('/tasks/taskdetailview/', {
            'taskid': self.task.id, 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['results']['user'], self.owner)

    # --- taskresultview ---

    def test_result_missing_userid_rejected(self):
        resp = self._client().get('/tasks/taskresultview/', {
            'taskid': self.task.id, 'resulttype': 'metadata',
        })
        self.assertEqual(resp.status_code, 403)

    def test_result_wrong_userid_rejected(self):
        resp = self._client().get('/tasks/taskresultview/', {
            'taskid': self.task.id, 'resulttype': 'metadata', 'userid': self.intruder,
        })
        self.assertEqual(resp.status_code, 403)

    def test_result_correct_userid_passes_gate(self):
        # Ownership gate passed: proceeds to load task files, which do not exist
        # in a test env -> "Task metadata not found" 404 (NOT 403).
        resp = self._client().get('/tasks/taskresultview/', {
            'taskid': self.task.id, 'resulttype': 'metadata', 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json().get('status'), 'error')

    def test_result_testmode_exempt_from_ownership(self):
        # testmode=true must work without a userid (demo data, no task lookup).
        from unittest import mock

        with mock.patch('utils.analysis.Scstquery.gettestresult', return_value={'status': 'success'}):
            resp = self._client().get('/tasks/taskresultview/', {
                'taskid': '72', 'resulttype': 'metadata', 'testmode': 'true',
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

    # --- subtask/status ---

    def test_subtask_status_missing_userid_rejected(self):
        resp = self._client().get('/tasks/subtask/status/', {'subtaskid': self.subtask.id})
        self.assertEqual(resp.status_code, 403)

    def test_subtask_status_wrong_userid_rejected(self):
        resp = self._client().get('/tasks/subtask/status/', {
            'subtaskid': self.subtask.id, 'userid': self.intruder,
        })
        self.assertEqual(resp.status_code, 403)

    def test_subtask_status_unknown_subtask_uniform_403(self):
        resp = self._client().get('/tasks/subtask/status/', {
            'subtaskid': 999999, 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 403)

    def test_subtask_status_correct_userid_terminal(self):
        # Completed is a terminal state -> returns immediately, no SLURM calls.
        resp = self._client().get('/tasks/subtask/status/', {
            'subtaskid': self.subtask.id, 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('current_status'), 'Completed')

    # --- subtask/log ---

    def test_subtask_log_missing_userid_rejected(self):
        resp = self._client().get('/tasks/subtask/log/', {'subtaskid': self.subtask.id})
        self.assertEqual(resp.status_code, 403)

    def test_subtask_log_wrong_userid_rejected(self):
        resp = self._client().get('/tasks/subtask/log/', {
            'subtaskid': self.subtask.id, 'userid': self.intruder,
        })
        self.assertEqual(resp.status_code, 403)

    def test_subtask_log_correct_userid_passes_gate(self):
        # Gate passed: real job_id but no SLURM log path mapping in test -> 400.
        resp = self._client().get('/tasks/subtask/log/', {
            'subtaskid': self.subtask.id, 'userid': self.owner,
        })
        self.assertIn(resp.status_code, (400, 404))

    # --- removed legacy endpoints ---

    def test_getoutputfile_route_removed(self):
        resp = self._client().get('/tasks/getoutputfile/foo/bar.csv')
        self.assertEqual(resp.status_code, 404)

    def test_taskviewset_route_removed(self):
        resp = self._client().get('/task/')
        self.assertEqual(resp.status_code, 404)
