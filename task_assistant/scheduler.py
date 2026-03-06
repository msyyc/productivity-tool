import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from task_assistant.models import Task, TaskStatus
from task_assistant.pr_monitor import check_ci_status, check_pr_state
from task_assistant.popup import show_popup

if TYPE_CHECKING:
    from task_assistant.storage import TaskStore


class Scheduler:
    def __init__(self, store: "TaskStore"):
        self.store = store
        self._running_tasks: dict[str, asyncio.Task] = {}

    async def start(self):
        """Resume all active tasks from storage."""
        for task in self.store.get_active():
            self.schedule(task)

    def schedule(self, task: Task):
        """Start monitoring/timing a task."""
        if task.id in self._running_tasks:
            return
        if task.type == "pr_monitor":
            self._running_tasks[task.id] = asyncio.create_task(self._run_pr_monitor(task))
        elif task.type == "reminder":
            self._running_tasks[task.id] = asyncio.create_task(self._run_reminder(task))

    def cancel(self, task_id: str):
        """Cancel a running background task."""
        t = self._running_tasks.pop(task_id, None)
        if t:
            t.cancel()

    async def _run_pr_monitor(self, task: Task):
        """Poll PR CI status until triggered, timed out, or cancelled."""
        cfg = task.pr_monitor
        if not cfg:
            return
        interval = cfg.poll_interval_minutes * 60
        expire_at = datetime.fromisoformat(cfg.expire_at) if cfg.expire_at else None
        try:
            while True:
                loop = asyncio.get_event_loop()
                state = await loop.run_in_executor(None, check_pr_state, cfg.repo, cfg.pr_number)
                ci = await loop.run_in_executor(None, check_ci_status, cfg.repo, cfg.pr_number)

                cfg.last_status = ci
                cfg.last_checked = datetime.now(timezone.utc).isoformat()
                self.store.update(task)

                pr_title = task.description or f"#{cfg.pr_number}"
                if state == "MERGED":
                    self._trigger(task, "PR Merged", f"{pr_title}\n#{cfg.pr_number} in {cfg.repo} has been merged!")
                    return
                if ci == "FAILURE":
                    self._trigger(task, "CI Failed", f"{pr_title}\nCI checks failed on #{cfg.pr_number} in {cfg.repo}")
                    return
                if ci == "ALL_COMPLETE":
                    if cfg.repo not in ("Azure/azure-rest-api-specs", "microsoft/typespec"):
                        self._trigger(task, "CI Passed", f"{pr_title}\nAll CI checks passed on #{cfg.pr_number} in {cfg.repo}")
                        return

                # Check timeout
                if expire_at and datetime.now(timezone.utc) >= expire_at:
                    status_msg = {"IN_PROGRESS": "still in progress", "ALL_COMPLETE": "all passed", "UNKNOWN": "unknown"}.get(ci, ci)
                    self._trigger(task, "⏰ PR Monitor Timeout",
                                  f"{pr_title}\nTime's up for #{cfg.pr_number} in {cfg.repo}\nCI status: {status_msg}")
                    return

                # Sleep until next poll or expiry, whichever is sooner
                sleep_secs = interval
                if expire_at:
                    remaining = (expire_at - datetime.now(timezone.utc)).total_seconds()
                    if remaining > 0:
                        sleep_secs = min(interval, remaining)
                await asyncio.sleep(sleep_secs)
        except asyncio.CancelledError:
            pass

    async def _run_reminder(self, task: Task):
        """Wait until fire_at time, then trigger popup."""
        cfg = task.reminder
        if not cfg:
            return
        try:
            fire_at = datetime.fromisoformat(cfg.fire_at)
            now = datetime.now(timezone.utc)
            delay = (fire_at - now).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            self._trigger(task, "⏰ Reminder", task.description)
        except asyncio.CancelledError:
            pass

    def _trigger(self, task: Task, title: str, message: str):
        """Show popup and update task status."""
        task.status = TaskStatus.TRIGGERED
        self.store.update(task)
        self._running_tasks.pop(task.id, None)

        def on_dismiss():
            task.status = TaskStatus.DISMISSED
            self.store.update(task)

        show_popup(title, message, task.link, on_dismiss=on_dismiss)
