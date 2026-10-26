import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from task_assistant.main import BREAKING_LABELS, _fetch_breaking_prs, _fetch_pr_title
from task_assistant.popup import _spawn_popup
from task_assistant.pr_monitor import check_ci_status, check_pr_state


class BackgroundProcessTests(unittest.TestCase):
    def test_github_commands_run_without_console_windows(self):
        pr = {
            "number": 123,
            "title": "Example",
            "url": "https://github.com/example/repo/pull/123",
            "labels": [],
        }
        cases = [
            (_fetch_pr_title, ("example/repo", 123), "Example", "Example", 1),
            (_fetch_breaking_prs, ("example/repo",), json.dumps([pr]), None, len(BREAKING_LABELS)),
            (check_pr_state, ("example/repo", 123), "OPEN", "OPEN", 1),
            (check_ci_status, ("example/repo", 123),
             '[{"name":"test","state":"SUCCESS"}]', "ALL_COMPLETE", 1),
        ]
        for function, args, output, expected, call_count in cases:
            with self.subTest(function=function.__name__):
                result = subprocess.CompletedProcess([], 0, output, "")
                with patch("subprocess.run", return_value=result) as run:
                    value = function(*args)
                if function is _fetch_breaking_prs:
                    self.assertEqual(len(value), 1)
                    self.assertEqual(value[0]["number"], 123)
                else:
                    self.assertEqual(value, expected)
                self.assertEqual(run.call_count, call_count)
                for call in run.call_args_list:
                    self.assertEqual(
                        call.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                    self.assertTrue(call.kwargs["capture_output"])

    def test_popup_still_dismisses_without_console_window(self):
        dismissed = Mock()
        result = subprocess.CompletedProcess([], 0, "dismissed", "")
        with patch("task_assistant.popup.subprocess.run", return_value=result) as run:
            _spawn_popup("Title", "Message", "https://example.com", dismissed)
        dismissed.assert_called_once_with()
        self.assertEqual(run.call_args.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
