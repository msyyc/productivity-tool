import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from task_assistant.email_notification import send_email
from task_assistant.models import PRMonitorConfig, ReminderConfig, Task, TaskStatus, TaskType
from task_assistant.scheduler import Scheduler
from task_assistant.storage import TaskStore


class EmailTests(unittest.TestCase):
    def test_helper_arguments_and_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper with spaces.ps1"
            helper.touch()
            with patch.dict(os.environ, {"TASK_ASSISTANT_EMAIL_HELPER": str(helper)}):
                with patch("task_assistant.email_notification.subprocess.run") as run:
                    run.return_value = subprocess.CompletedProcess([], 0, '{"status":"sent","messageId":"123"}', "")
                    send_email("Reminder", "Don't forget\nDetails", "https://example.com")
                    args = run.call_args.args[0]
                    self.assertEqual(args[:5], ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(helper)])
                    self.assertEqual(args[5:], [
                        "-Subject", "Reminder",
                        "-Body", "https://example.com",
                    ])
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_exact_status_subjects_and_link_only_body(self):
        link = 'https://example.com/?a=1&b="quoted"&c=<tag>'
        for title, expected in [
            ("\u23f0 Reminder", "Timeout"),
            ("\u23f0 PR Monitor Timeout", "Timeout"),
            ("CI Failed", "CI fails"),
            ("CI Passed", "CI passes"),
            ("PR Merged", "PR merged"),
        ]:
            with self.subTest(title=title):
                with patch("task_assistant.email_notification.Path.is_file", return_value=True):
                    with patch("task_assistant.email_notification.subprocess.run") as run:
                        run.return_value = subprocess.CompletedProcess([], 0, '{"status":"sent","messageId":"123"}', "")
                        send_email(title, "Description must not appear in body", link)
                        args = run.call_args.args[0]
                        self.assertEqual(args[args.index("-Subject") + 1], expected)
                        self.assertEqual(args[args.index("-Body") + 1], link)
                        self.assertNotIn("-ContentType", args)

    def test_failures_never_retry(self):
        with patch("task_assistant.email_notification.Path.is_file", return_value=True):
            for result in [
                subprocess.CompletedProcess([], 1, "", "Access denied"),
                subprocess.CompletedProcess([], 0, "invalid json", ""),
                subprocess.CompletedProcess([], 0, "[]", ""),
                subprocess.CompletedProcess([], 0, '{"status":"sent"}', ""),
                subprocess.CompletedProcess([], 0, '{"status":"not-sent","messageId":"123"}', ""),
            ]:
                with self.subTest(result=result):
                    with patch("task_assistant.email_notification.subprocess.run", return_value=result) as run:
                        with self.assertRaises((RuntimeError, ValueError)):
                            send_email("Title", "Body", "Link")
                        self.assertEqual(run.call_count, 1)
            with patch(
                "task_assistant.email_notification.subprocess.run",
                side_effect=subprocess.TimeoutExpired("pwsh", 120),
            ) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    send_email("Title", "Body", "Link")
                self.assertEqual(run.call_count, 1)

    def test_missing_helper_does_not_launch(self):
        with patch("task_assistant.email_notification.Path.is_file", return_value=False):
            with patch("task_assistant.email_notification.subprocess.run") as run:
                with self.assertRaises(FileNotFoundError):
                    send_email("Title", "Body", "Link")
                run.assert_not_called()


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"
        self.store = TaskStore(self.path)
        with patch.dict(os.environ, {}, clear=True):
            self.scheduler = Scheduler(self.store)
        self.task = Task(type=TaskType.REMINDER, description="Follow up", link="https://example.com")
        self.store.add(self.task)

    async def test_default_email_and_persisted_status(self):
        with patch("task_assistant.scheduler.send_email") as email, patch("task_assistant.scheduler.show_popup") as popup:
            await self.scheduler._trigger(self.task, "Reminder", self.task.description)
            email.assert_called_once_with("Reminder", "Follow up", self.task.link)
            popup.assert_not_called()
        self.assertEqual(TaskStore(self.path).get(self.task.id).status, TaskStatus.TRIGGERED)
        self.assertNotIn(self.task.id, self.scheduler._running_tasks)

    async def test_failure_is_persisted_and_not_resumed(self):
        with patch("task_assistant.scheduler.send_email", side_effect=RuntimeError("Denied")) as email:
            with patch("task_assistant.scheduler.show_popup") as popup:
                with self.assertLogs("task_assistant.scheduler", level="ERROR"):
                    await self.scheduler._trigger(self.task, "Reminder", "Body")
                email.assert_called_once()
                popup.assert_not_called()
        restored = TaskStore(self.path)
        failed = restored.get(self.task.id)
        self.assertEqual(failed.status, TaskStatus.ERROR)
        self.assertIn("Denied", failed.notification_error)
        self.assertIn("Sent Items", failed.notification_error)
        scheduler = Scheduler(restored)
        await scheduler.start()
        self.assertFalse(scheduler._running_tasks)

    async def test_popup_opt_in_preserves_dismiss(self):
        self.scheduler.notification_mode = "popup"
        with patch("task_assistant.scheduler.show_popup") as popup, patch("task_assistant.scheduler.send_email") as email:
            await self.scheduler._trigger(self.task, "Reminder", "Body")
            popup.assert_called_once()
            popup.call_args.kwargs["on_dismiss"]()
            email.assert_not_called()
        self.assertEqual(TaskStore(self.path).get(self.task.id).status, TaskStatus.DISMISSED)

    async def test_legacy_task_loads_with_email_default(self):
        data = self.task.model_dump()
        data.pop("notification_error")
        self.path.write_text(json.dumps([data]), encoding="utf-8")
        loaded = TaskStore(self.path).get(self.task.id)
        self.assertIsNone(loaded.notification_error)
        self.assertEqual(self.scheduler.notification_mode, "email")

    async def test_reminder_and_all_pr_triggers(self):
        self.task.reminder = ReminderConfig(delay_minutes=0, fire_at=datetime.now(timezone.utc).isoformat())
        with patch("task_assistant.scheduler.send_email") as email:
            await self.scheduler._run_reminder(self.task)
            email.assert_called_once()

        for state, ci, repo, expected in [
            ("MERGED", "ALL_COMPLETE", "owner/repo", "PR Merged"),
            ("OPEN", "FAILURE", "owner/repo", "CI Failed"),
            ("OPEN", "ALL_COMPLETE", "owner/repo", "CI Passed"),
            ("OPEN", "IN_PROGRESS", "owner/repo", "Timeout"),
            ("OPEN", "ALL_COMPLETE", "Azure/azure-rest-api-specs", "Timeout"),
            ("OPEN", "ALL_COMPLETE", "microsoft/typespec", "Timeout"),
        ]:
            with self.subTest(state=state, ci=ci, repo=repo):
                task = Task(
                    type=TaskType.PR_MONITOR, link="https://example.com/pr",
                    pr_monitor=PRMonitorConfig(
                        repo=repo, pr_number=1, expire_at=datetime.now(timezone.utc).isoformat(),
                    ),
                )
                self.store.add(task)
                with patch("task_assistant.scheduler.check_pr_state", return_value=state):
                    with patch("task_assistant.scheduler.check_ci_status", return_value=ci):
                        with patch("task_assistant.scheduler.send_email") as email:
                            await self.scheduler._run_pr_monitor(task)
                            email.assert_called_once()
                            self.assertIn(expected, email.call_args.args[0])

    async def test_email_does_not_block_event_loop(self):
        import threading

        started = threading.Event()
        release = threading.Event()

        def blocking_send(*args):
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release email worker")

        with patch("task_assistant.scheduler.send_email", side_effect=blocking_send):
            trigger = asyncio.create_task(self.scheduler._trigger(self.task, "Title", "Body"))
            try:
                for _ in range(100):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(started.is_set())
                self.assertFalse(trigger.done())
            finally:
                release.set()
                await trigger

    def test_invalid_notification_mode(self):
        with patch.dict(os.environ, {"TASK_ASSISTANT_NOTIFICATION": "invalid"}):
            with self.assertRaises(ValueError):
                Scheduler(self.store)


if __name__ == "__main__":
    unittest.main()
