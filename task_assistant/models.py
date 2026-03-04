import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    PR_MONITOR = "pr_monitor"
    REMINDER = "reminder"


class TaskStatus(str, Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    DISMISSED = "dismissed"
    ERROR = "error"


class PRMonitorConfig(BaseModel):
    repo: str
    pr_number: int
    watch_for: list[str] = Field(default_factory=lambda: ["ci_failure", "ci_success", "merged"])
    poll_interval_minutes: int = 5
    timeout_minutes: int = 30
    expire_at: Optional[str] = None  # ISO timestamp
    filter_checks: Optional[list[str]] = None
    last_status: Optional[str] = None
    last_checked: Optional[str] = None


class ReminderConfig(BaseModel):
    delay_minutes: int
    fire_at: str  # ISO timestamp


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: TaskType
    description: str = ""
    link: str
    status: TaskStatus = TaskStatus.ACTIVE
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pr_monitor: Optional[PRMonitorConfig] = None
    reminder: Optional[ReminderConfig] = None


class CreateTaskRequest(BaseModel):
    type: TaskType
    link: str
    description: str = ""
    delay_minutes: Optional[int] = None  # for reminders
    timeout_minutes: Optional[int] = None  # for PR monitors (default 30)
