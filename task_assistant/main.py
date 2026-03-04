import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from task_assistant.models import (
    Task, TaskType, TaskStatus, PRMonitorConfig, ReminderConfig, CreateTaskRequest,
)
from task_assistant.storage import TaskStore
from task_assistant.scheduler import Scheduler
from task_assistant.tray import start_tray_thread

store = TaskStore()
scheduler = Scheduler(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_tray_thread()
    await scheduler.start()
    yield


app = FastAPI(title="Task Assistant", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/tasks")
async def list_tasks():
    return [t.model_dump() for t in store.get_all()]


@app.post("/api/tasks")
async def create_task(req: CreateTaskRequest):
    task = Task(type=req.type, link=req.link, description=req.description)

    if req.type == TaskType.PR_MONITOR:
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", req.link.split("?")[0].split("#")[0])
        if not m:
            raise HTTPException(400, "Invalid GitHub PR URL")
        timeout = req.timeout_minutes or 30
        expire_at = datetime.now(timezone.utc) + timedelta(minutes=timeout)
        task.pr_monitor = PRMonitorConfig(
            repo=m.group(1), pr_number=int(m.group(2)),
            timeout_minutes=timeout, expire_at=expire_at.isoformat(),
        )

    elif req.type == TaskType.REMINDER:
        if not req.delay_minutes or req.delay_minutes <= 0:
            raise HTTPException(400, "delay_minutes must be a positive integer")
        fire_at = datetime.now(timezone.utc) + timedelta(minutes=req.delay_minutes)
        task.reminder = ReminderConfig(delay_minutes=req.delay_minutes, fire_at=fire_at.isoformat())

    store.add(task)
    scheduler.schedule(task)
    return task.model_dump()


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    scheduler.cancel(task_id)
    task.status = TaskStatus.DISMISSED
    store.update(task)
    return {"ok": True}


@app.get("/api/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump()


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8347, log_level="info")


if __name__ == "__main__":
    main()
