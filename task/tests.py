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

    # --- taskresultview / runSummary ---

    def test_runsummary_wrong_userid_rejected(self):
        resp = self._client().get('/tasks/taskresultview/', {
            'taskid': self.task.id, 'resulttype': 'runSummary', 'userid': self.intruder,
        })
        self.assertEqual(resp.status_code, 403)

    def test_runsummary_owner_returns_summary(self):
        # taskdetail.json does not exist in the test env -> module falls back
        # to the DB row; parameters stay empty; the subtask timeline comes
        # from the SubTask rows.
        resp = self._client().get('/tasks/taskresultview/', {
            'taskid': self.task.id, 'resulttype': 'runSummary', 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        data = body['data']
        self.assertEqual(data['module'], 'Scstquery')
        self.assertEqual(data['parameters'], {})
        self.assertEqual(len(data['subtasks']), 1)
        self.assertEqual(data['subtasks'][0]['subtask_type'], 'cellchat')
        self.assertEqual(data['subtasks'][0]['status'], 'Completed')

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


class SlurmSubmitJobTests(TestCase):
    """submit_job must return the parsed job id.

    Regression: the original `return job_id` line was orphaned into cancel_job's
    body, so submit_job returned None -> taskdetail.json got job_id null -> the
    scheduled sync treated every fresh task as metadata-less and deleted it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()
        from utils.slurm_api import submit_job

        cls.submit_job = staticmethod(submit_job)

    def test_submit_job_returns_parsed_job_id(self):
        from unittest import mock

        with mock.patch('utils.slurm_api.subprocess.check_output',
                        return_value=b'Submitted batch job 12345\n'):
            job_id = self.submit_job('/fake/run.sh', script_arguments=['a', 'b'])
        self.assertEqual(job_id, '12345')

    def test_submit_job_with_dependencies_builds_afterok_chain(self):
        from unittest import mock

        commands = []

        def fake_check_output(cmd, **kwargs):
            commands.append(cmd)
            return b'Submitted batch job 777\n'

        with mock.patch('utils.slurm_api.subprocess.check_output',
                        side_effect=fake_check_output):
            job_id = self.submit_job('/fake/run.sh', dependency_job_ids=[11, 22])
        self.assertEqual(job_id, '777')
        self.assertIn('--dependency=afterok:11:22', commands[0])
        self.assertIn('--kill-on-invalid-dep=yes', commands[0])

    def test_submit_job_sbatch_failure_propagates(self):
        import subprocess as subprocess_mod
        from unittest import mock

        with mock.patch('utils.slurm_api.subprocess.check_output',
                        side_effect=subprocess_mod.CalledProcessError(1, 'sbatch')):
            with self.assertRaises(subprocess_mod.CalledProcessError):
                self.submit_job('/fake/run.sh')


class ModuleProcessStoresJobIdTests(TestCase):
    """Module.process must persist the id returned by submit_job (P0 chain)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()
        from task.models import TaskStatus
        from utils.analysis.base import Module

        cls.Module = Module
        cls.TaskStatus = TaskStatus

    def test_process_stores_returned_job_id(self):
        from unittest import mock

        mod = self.Module('m', '/tmp/nonexistent-task')
        mod.shell_script = '/fake/run.sh'
        mod.script_arguments = None
        with mock.patch('utils.slurm_api.submit_job', return_value='555') as submit:
            returned = mod.process()
        submit.assert_called_once()
        self.assertEqual(returned, '555')
        self.assertEqual(mod.job_id, '555')
        self.assertEqual(mod.status, self.TaskStatus.RUNNING)


class ScheduledJobIdPreservationTests(TestCase):
    """Scheduled sync: a Running task whose taskdetail.json carries a real job_id
    must survive the sweep; only metadata-less tasks are cleaned up."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def setUp(self):
        from task.models import tasks as task_model

        self._tmp = tempfile.mkdtemp()
        self.task_row = task_model.objects.create(
            name='sched', user='u', userpath='sched_0001',
            task_type='module', status='Running', modulelist='Scstquery',
        )
        self._task_model = task_model

    def tearDown(self):
        self._task_model.objects.filter(id=self.task_row.id).delete()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_taskdir(self, userpath, job_id):
        import json

        task_dir = os.path.join(self._tmp, userpath)
        os.makedirs(task_dir, exist_ok=True)
        detail = {'modulename': 'Scstquery', 'status': 'Running'}
        if job_id is not None:
            detail['job_id'] = job_id
        with open(os.path.join(task_dir, 'taskdetail.json'), 'w') as f:
            json.dump([detail], f)

    def _run_scheduled(self, slurm_status):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command
        from task.management.commands import scheduled as scheduled_mod

        # _append_change_log writes to the real server-side update.txt; keep the
        # test from polluting it.
        with mock.patch.object(scheduled_mod.local_settings, 'USERTASKPATH', self._tmp + '/'), \
                mock.patch.object(scheduled_mod.Command, '_append_change_log', lambda self, msg: None), \
                mock.patch.object(scheduled_mod, 'slurm_get_job_status', return_value=slurm_status):
            call_command('scheduled', stdout=StringIO())

    def test_task_with_real_job_id_survives_sync(self):
        self._write_taskdir('sched_0001', '424242')
        self._run_scheduled('RUNNING')
        self.assertTrue(self._task_model.objects.filter(id=self.task_row.id).exists())
        row = self._task_model.objects.get(id=self.task_row.id)
        self.assertEqual((row.status or '').lower(), 'running')

    def test_task_without_job_id_metadata_is_cleaned_up(self):
        self._write_taskdir('sched_0001', None)
        self._run_scheduled('RUNNING')
        self.assertFalse(self._task_model.objects.filter(id=self.task_row.id).exists())


class ScqueryDownloadSecurityTests(TestCase):
    """Legacy Scquery.download: bare-name contract + the shared traversal/symlink
    guards (the front-end entry is hidden, but backend security must not rely
    on that)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()
        from utils.analysis.scquery import Scquery

        cls.Scquery = Scquery

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.task_root = os.path.join(self._tmp, 'task')
        # __new__ bypasses __init__ (which reads settings_local / params);
        # download() only needs self.path.
        self.mod = self.Scquery.__new__(self.Scquery)
        self.mod.path = self.task_root
        self._make_file('result/sc_marker', 'X_marker.csv', b'csv-content')
        self._make_file('result/sc_query/annotation_h5ad', 'ann.h5ad', b'h5ad-bytes')
        self._make_file('result/meta', 'meta.txt', b'txt-content')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_file(self, rel_dir, name, content):
        d = os.path.join(self.task_root, rel_dir)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), 'wb') as f:
            f.write(content)

    def _download(self, filename):
        return self.mod.download(filename)

    def _assert_success(self, res, expect_bytes):
        self.assertEqual(res.get('status'), 'success', res)
        import base64
        self.assertEqual(base64.b64decode(res['file_content']), expect_bytes)

    def test_legitimate_files_still_download(self):
        self._assert_success(self._download('X_marker.csv'), b'csv-content')
        self._assert_success(self._download('ann.h5ad'), b'h5ad-bytes')
        self._assert_success(self._download('meta.txt'), b'txt-content')

    def test_parent_traversal_rejected(self):
        outside = os.path.join(self._tmp, 'secret.txt')
        with open(outside, 'wb') as f:
            f.write(b'secret')
        for bad in ('../secret.txt', '../../secret.txt', '..%2fsecret.txt'):
            res = self._download(bad)
            self.assertEqual(res.get('status'), 'fail', bad)

    def test_absolute_path_rejected(self):
        res = self._download('/tmp/secret.txt')
        self.assertEqual(res.get('status'), 'fail')

    def test_subdirectory_path_rejected(self):
        # Scquery's legacy contract is bare filenames only
        res = self._download('result/meta/meta.txt')
        self.assertEqual(res.get('status'), 'fail')

    def test_symlink_escape_rejected(self):
        outside = os.path.join(self._tmp, 'outside.txt')
        with open(outside, 'wb') as f:
            f.write(b'outside')
        os.symlink(outside, os.path.join(self.task_root, 'result', 'meta', 'escape.txt'))
        res = self._download('escape.txt')
        self.assertEqual(res.get('status'), 'fail')

    def test_internal_metadata_excluded(self):
        self._make_file('', 'taskdetail.json', b'{}')
        res = self._download('taskdetail.json')
        self.assertEqual(res.get('status'), 'fail')

    def test_missing_file_fails_cleanly(self):
        res = self._download('no_such.csv')
        self.assertEqual(res.get('status'), 'fail')

    def test_unknown_extension_fails_without_error(self):
        # the old implementation raised NameError (filepath never assigned)
        res = self._download('weird.exe')
        self.assertEqual(res.get('status'), 'fail')

    def test_empty_filename_rejected(self):
        res = self._download('')
        self.assertEqual(res.get('status'), 'fail')


class ParameterValidationTests(TestCase):
    """Missing / malformed params must return 400 (or uniform 403 for unknown
    ids), never an unhandled-exception 500."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
        import django

        django.setup()

    def setUp(self):
        from task.models import SubTask, TaskStatus, tasks as task_model

        self.owner = 'owner_val'
        self.task = task_model.objects.create(
            name='val', user=self.owner, userpath='val123_0001',
            task_type='module', status='Completed', modulelist='Scstquery',
        )
        self.subtask = SubTask.objects.create(
            main_task=self.task, subtask_type='cellchat',
            dataset_path='ds_x', status=TaskStatus.COMPLETED, job_id='1234567',
        )
        self._task_model = task_model

    def tearDown(self):
        self._task_model.objects.filter(id=self.task.id).delete()

    def _client(self):
        from django.test import Client

        return Client()

    def test_task_list_missing_userid_400(self):
        for path in ('/tasks/list/', '/tasks/detail/'):
            resp = self._client().get(path)
            self.assertEqual(resp.status_code, 400, path)

    def test_taskdetail_non_integer_taskid_400(self):
        resp = self._client().get('/tasks/taskdetailview/', {
            'taskid': 'abc', 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 400)

    def test_taskresult_non_integer_taskid_400(self):
        resp = self._client().get('/tasks/taskresultview/', {
            'taskid': 'abc', 'userid': self.owner, 'resulttype': 'metadata',
        })
        self.assertEqual(resp.status_code, 400)

    def test_subtask_status_non_integer_id_400(self):
        resp = self._client().get('/tasks/subtask/status/', {
            'subtaskid': 'abc', 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 400)

    def test_subtask_log_non_integer_id_400(self):
        resp = self._client().get('/tasks/subtask/log/', {
            'subtaskid': 'abc', 'userid': self.owner,
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_subtask_unknown_task_uniform_403(self):
        resp = self._client().post('/tasks/createsubtask/', {
            'taskid': 999999, 'userid': self.owner,
            'dataset_id': 'DS_X', 'subtasktype': 'cellchat',
            'parameters': '{}',
        })
        self.assertEqual(resp.status_code, 403)

    def test_create_subtask_non_integer_taskid_400(self):
        resp = self._client().post('/tasks/createsubtask/', {
            'taskid': 'abc', 'userid': self.owner,
            'dataset_id': 'DS_X', 'subtasktype': 'cellchat',
            'parameters': '{}',
        })
        self.assertEqual(resp.status_code, 400)

    def test_createtask_missing_field_400_and_no_orphan_dir(self):
        import tempfile
        from unittest import mock

        from django.test import Client
        import task.views as views

        tmp_workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_workspace, ignore_errors=True)

        c = Client()
        with mock.patch.object(views.local_settings, 'USERTASKPATH', tmp_workspace + '/'):
            # everything except parameters -> rejected before any directory exists
            resp = c.post('/tasks/createtask/', {
                'taskname': 't', 'userid': 'u',
                'tasktype': 'module', 'modulename': 'Scstquery',
            })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(os.listdir(tmp_workspace), [])

    def test_createtask_invalid_parameters_json_400_cleans_dir(self):
        import tempfile
        from unittest import mock

        from django.test import Client
        import task.views as views

        tmp_workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_workspace, ignore_errors=True)

        upload_path = os.path.join(tmp_workspace, 'input.h5ad')
        import h5py
        with h5py.File(upload_path, 'w') as hf:
            for k in ('X', 'obs', 'var'):
                hf.create_dataset(k, data=[1, 2, 3])

        c = Client()
        with mock.patch.object(views.local_settings, 'USERTASKPATH', tmp_workspace + '/'):
            with open(upload_path, 'rb') as f:
                resp = c.post('/tasks/createtask/', {
                    'submitfile': f,
                    'parameters': '{not valid json',
                    'taskname': 't', 'userid': 'u',
                    'tasktype': 'module', 'modulename': 'Scstquery',
                })
        self.assertEqual(resp.status_code, 400)
        # the uploaded task dir must not be left behind
        leftovers = [p for p in os.listdir(tmp_workspace) if p != 'input.h5ad']
        self.assertEqual(leftovers, [])
