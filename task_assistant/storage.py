import json
import threading
from pathlib import Path
from typing import Optional
from task_assistant.models import Task

STORAGE_FILE = Path(__file__).parent / "tasks.json"


class TaskStore:
    def __init__(self, path: Path = STORAGE_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            with open(self._path, "r") as f:
                data = json.load(f)
            self._tasks = {t["id"]: Task(**t) for t in data}

    def _save(self):
        with open(self._path, "w") as f:
            json.dump([t.model_dump() for t in self._tasks.values()], f, indent=2)

    def add(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.id] = task
            self._save()
        return task

    def remove(self, task_id: str) -> Optional[Task]:
        with self._lock:
            task = self._tasks.pop(task_id, None)
            if task:
                self._save()
            return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_all(self) -> list[Task]:
        return list(self._tasks.values())

    def get_active(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "active"]

    def update(self, task: Task):
        with self._lock:
            self._tasks[task.id] = task
            self._save()
