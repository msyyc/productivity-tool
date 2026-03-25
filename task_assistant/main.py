import re
import asyncio
import json
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from task_assistant.models import (
    Task,
    TaskType,
    TaskStatus,
    PRMonitorConfig,
    ReminderConfig,
    CreateTaskRequest,
)
from task_assistant.storage import TaskStore, AnnotationStore
from task_assistant.scheduler import Scheduler
from task_assistant.tray import start_tray_thread

store = TaskStore()
annotation_store = AnnotationStore()
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

    # Auto-fill description with PR title if link is a GitHub PR URL
    pr_match = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", req.link.split("?")[0].split("#")[0])
    if pr_match and not req.description:
        loop = asyncio.get_event_loop()
        title = await loop.run_in_executor(None, _fetch_pr_title, pr_match.group(1), int(pr_match.group(2)))
        if title:
            task.description = title

    if req.type == TaskType.PR_MONITOR:
        if not pr_match:
            raise HTTPException(400, "Invalid GitHub PR URL")
        timeout = req.timeout_minutes or 30
        expire_at = datetime.now(timezone.utc) + timedelta(minutes=timeout)
        task.pr_monitor = PRMonitorConfig(
            repo=pr_match.group(1),
            pr_number=int(pr_match.group(2)),
            timeout_minutes=timeout,
            expire_at=expire_at.isoformat(),
        )

    elif req.type == TaskType.REMINDER:
        if req.delay_minutes is None or req.delay_minutes < 0:
            raise HTTPException(400, "delay_minutes must be a non-negative integer")
        fire_at = datetime.now(timezone.utc) + timedelta(minutes=req.delay_minutes)
        task.reminder = ReminderConfig(delay_minutes=req.delay_minutes, fire_at=fire_at.isoformat())

    store.add(task)
    scheduler.schedule(task)
    return task.model_dump()


@app.delete("/api/tasks/history")
async def clear_history():
    for task in store.get_all():
        if task.status != TaskStatus.ACTIVE:
            store.remove(task.id)
    return {"ok": True}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    scheduler.cancel(task_id)
    task.status = TaskStatus.DISMISSED
    store.update(task)
    return {"ok": True}


@app.patch("/api/tasks/{task_id}/annotation")
async def update_annotation(task_id: str, body: dict):
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.annotation = body.get("annotation", "")
    store.update(task)
    return {"ok": True}


@app.get("/api/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump()


BREAKING_LABELS = [
    "CI-BreakingChange-Python-Track2",
    "CI-BreakingChange-Python",
    "BreakingChange-Python-Sdk",
    "BreakingChange-Python-Sdk-Suppression",
]
APPROVED_LABELS = [
    "Approved-SdkBreakingChange-Python",
    "BreakingChange-Python-Sdk-Suppression-Approved",
    "BreakingChange-Python-Sdk-Approved",
]
BREAKING_REPOS = [
    "Azure/azure-rest-api-specs",
    "Azure/azure-rest-api-specs-pr",
]


def _fetch_pr_title(repo: str, pr_number: int) -> str:
    """Fetch a PR title using gh CLI. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "title", "--jq", ".title"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _fetch_breaking_prs(repo: str) -> list[dict]:
    """Fetch open breaking change PRs for a repo using gh CLI.
    Queries each breaking label separately since gh --label is AND not OR.
    """
    seen = set()
    all_prs = []
    for label in BREAKING_LABELS:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--state",
                    "open",
                    "--label",
                    label,
                    "--label",
                    "ARMSignedOff",
                    "--json",
                    "number,title,url,labels,author,createdAt",
                    "--limit",
                    "50",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                continue
            prs = json.loads(result.stdout) if result.stdout.strip() else []
            for pr in prs:
                if pr["number"] in seen:
                    continue
                seen.add(pr["number"])
                pr_labels = {l["name"] for l in pr.get("labels", [])}
                if not pr_labels.intersection(APPROVED_LABELS):
                    all_prs.append(
                        {
                            "number": pr["number"],
                            "title": pr["title"],
                            "url": pr["url"],
                            "author": pr.get("author", {}).get("login", ""),
                            "created_at": pr.get("createdAt", ""),
                            "repo": repo,
                        }
                    )
        except Exception:
            continue
    return all_prs


@app.get("/api/breaking-prs")
async def list_breaking_prs():
    loop = asyncio.get_event_loop()
    results = await asyncio.gather(*[loop.run_in_executor(None, _fetch_breaking_prs, repo) for repo in BREAKING_REPOS])
    all_prs = []
    for prs in results:
        all_prs.extend(prs)
    annotations = annotation_store.get_all()
    for pr in all_prs:
        key = f"{pr['repo']}#{pr['number']}"
        pr["annotation"] = annotations.get(key, "")
    return all_prs


@app.patch("/api/breaking-prs/{repo_owner}/{repo_name}/{pr_number}/annotation")
async def update_breaking_pr_annotation(repo_owner: str, repo_name: str, pr_number: int, body: dict):
    key = f"{repo_owner}/{repo_name}#{pr_number}"
    annotation_store.set(key, body.get("annotation", ""))
    return {"ok": True}


def main():
    import uvicorn

    uvicorn.run(
        "task_assistant.main:app",
        host="127.0.0.1",
        port=8347,
        log_level="info",
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
    )


if __name__ == "__main__":
    main()
