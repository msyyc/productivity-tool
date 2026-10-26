import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from task_assistant.main import main


LAUNCHER = Path(__file__).resolve().parents[1] / "run.pyw"


class LauncherTests(unittest.TestCase):
    def test_windowless_startup_has_streams_and_no_reload(self):
        def start(**kwargs):
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)
            print("Startup output")

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                with patch("task_assistant.main.main", side_effect=start) as run:
                    with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
                        runpy.run_path(str(LAUNCHER), run_name="__main__")
                        self.assertIsNone(sys.stdout)
                        self.assertIsNone(sys.stderr)
                run.assert_called_once_with(reload=False)
            log = Path(directory) / "TaskAssistant" / "startup.log"
            self.assertIn("Startup output", log.read_text(encoding="utf-8"))

    def test_startup_failure_is_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                with patch("task_assistant.main.main", side_effect=RuntimeError("Startup failed")):
                    with self.assertRaisesRegex(RuntimeError, "Startup failed"):
                        runpy.run_path(str(LAUNCHER), run_name="__main__")
            log = Path(directory) / "TaskAssistant" / "startup.log"
            self.assertIn("RuntimeError: Startup failed", log.read_text(encoding="utf-8"))

    def test_console_reload_is_preserved(self):
        with patch("uvicorn.run") as run:
            main()
            self.assertTrue(run.call_args.kwargs["reload"])
            main(reload=False)
            self.assertFalse(run.call_args.kwargs["reload"])
            self.assertIsNone(run.call_args.kwargs["reload_dirs"])
