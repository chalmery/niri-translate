import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication
from niri_translate.runtime import Runtime


class RuntimeFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.runtime = Runtime()
        self.proc = Mock()
        self.runtime.process = self.proc
        self.runtime.backend = 'GPU · AMD'
        self.runtime.loaded_path = Path('/tmp/model.gguf')

    def tearDown(self):
        self.runtime.deleteLater()

    def test_gpu_failure_retries_same_model_once_on_cpu(self):
        with patch.object(self.runtime, '_start') as start:
            self.runtime._finished(self.proc, 1)
            self.assertTrue(self.runtime.fallback)
            self.assertEqual(self.runtime.desired, Path('/tmp/model.gguf'))
            start.assert_called_once()
            self.runtime.desired = None
            self.runtime.backend = 'CPU'
            self.runtime.process = self.proc
            self.runtime._finished(self.proc, 1)
            self.assertEqual(start.call_count, 1)

    def test_stop_does_not_reload(self):
        self.runtime.stopping = True
        with patch.object(self.runtime, '_start') as start:
            self.runtime._finished(self.proc, 0)
            start.assert_not_called()
            self.assertFalse(self.runtime.fallback)

    def test_switch_keeps_requested_model(self):
        self.runtime.stopping = True
        self.runtime.desired = Path('/tmp/other.gguf')
        with patch.object(self.runtime, '_start') as start:
            self.runtime._finished(self.proc, 0)
            self.assertEqual(self.runtime.desired, Path('/tmp/other.gguf'))
            self.assertFalse(self.runtime.fallback)
            start.assert_called_once()

    def test_old_process_exit_is_ignored(self):
        with patch.object(self.runtime, '_start') as start:
            self.runtime._finished(Mock(), 1)
            self.assertIs(self.runtime.process, self.proc)
            start.assert_not_called()
