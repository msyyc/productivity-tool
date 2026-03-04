# Task Assistant — Design Document

## Problem

Developer needs a background assistant for routine monitoring and reminders:
1. Monitor PR CI status and alert on failure/completion
2. Set timed reminders with links (Teams, Outlook, etc.)
3. Easy add/remove via a web dashboard
4. System tray icon for quick access and native popup alerts

## Approach

**Python + FastAPI + Web Dashboard + System Tray**

A single Python process running:
- FastAPI server on `localhost:8347` serving a web dashboard and REST API
- Background asyncio tasks for PR polling and timer countdowns
- System tray icon via `pystray` for quick dashboard access
- tkinter popups for always-on-top notifications

## Architecture

```
┌──────────────┐     ┌─────────────────────────┐     ┌──────────────┐
│  System Tray  │     │   FastAPI Server         │     │  Browser UI  │
│  (pystray)    │────▶│   localhost:8347         │◀────│  Dashboard   │
│  + tkinter    │     │                         │     │  (HTML/JS)   │
│  popups       │     │  ┌─────────────────┐    │     └──────────────┘
└──────────────┘     │  │ Task Scheduler   │    │
                      │  │ (asyncio tasks)  │    │
                      │  │ • PR CI poller  │    │
                      │  │ • Timer runner  │    │
                      │  └─────────────────┘    │
                      │  ┌─────────────────┐    │
                      │  │ tasks.json      │    │
                      │  └─────────────────┘    │
                      └─────────────────────────┘
```

## Data Model

```json
{
  "id": "uuid",
  "type": "pr_monitor | reminder",
  "description": "Free text description",
  "link": "URL",
  "status": "active | triggered | dismissed",
  "created_at": "ISO timestamp",
  "pr_monitor": {
    "repo": "owner/repo",
    "pr_number": 1234,
    "watch_for": ["ci_failure", "ci_success", "merged"],
    "poll_interval_minutes": 5,
    "filter_checks": null
  },
  "reminder": {
    "delay_minutes": 30,
    "fire_at": "ISO timestamp"
  }
}
```

### PR Monitor Behavior
- Extracts repo + PR number from GitHub URL
- Polls every 5 minutes via `gh pr checks`
- Special handling for `Azure/azure-rest-api-specs` (only watches "SDK Validation - Python")
- Triggers on: CI failure, all checks passed, or PR merged

### Reminder Behavior
- User provides a link + delay in minutes
- Fires popup with clickable link when time is up

## Web Dashboard

Single-page HTML/JS dashboard served by FastAPI:
- Lists active tasks with live status
- "+ Add" button with form (choose type, paste link, set delay)
- "✕" button to dismiss/remove tasks
- History section for triggered/dismissed tasks
- Auto-refreshes every 10 seconds

## REST API

```
GET  /api/tasks              → list all tasks
POST /api/tasks              → create a new task
DELETE /api/tasks/{id}       → dismiss/remove a task
GET  /api/tasks/{id}/status  → get current status
GET  /                       → serve dashboard HTML
```

## Popup Notifications

- Always-on-top tkinter window, centered on screen
- Shows task description + clickable link
- Click link → opens browser, closes popup
- "Dismiss" button → closes popup, marks task dismissed
- Multiple popups queued (one at a time)

## Error Handling

| Scenario | Behavior |
|---|---|
| `gh` CLI not available | Disable PR monitor, show error |
| GitHub rate limit | Back off to 15 min polling |
| PR deleted / repo not found | Mark task as error, stop polling |
| Network offline | Keep retrying, show "offline" badge |
| App restart | Resume from tasks.json, recalculate timers from fire_at |
| Multiple popups | Queue, show one at a time |

## File Structure

```
task_assistant/
  __init__.py
  main.py          # FastAPI app + startup
  tray.py          # System tray icon (pystray)
  popup.py         # tkinter popup windows
  scheduler.py     # Background task scheduler
  pr_monitor.py    # PR CI polling logic
  reminder.py      # Timer/reminder logic
  models.py        # Task data models
  storage.py       # JSON file persistence
  static/
    index.html     # Dashboard SPA
    style.css
    app.js
```

## Dependencies

- `fastapi`
- `uvicorn`
- `pystray`
- `Pillow`
