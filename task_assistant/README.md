# Task Assistant

A background task assistant with a web dashboard, system tray icon, and email notifications by default. Helps developers monitor PR CI status and set timed reminders.

## Features

- **PR CI Monitor** — Watch GitHub PR CI checks and get alerted on failure, success, or merge
  - Special handling for `Azure/azure-rest-api-specs` (only watches "SDK Validation - Python")
  - Polls every 5 minutes via `gh` CLI
- **Timed Reminder** — Paste a link (Teams, Outlook, etc.) and set a delay; get an email when time's up
- **Web Dashboard** — Add/remove tasks, see live CI status, view history at `http://localhost:8347`
- **System Tray Icon** — Right-click to open dashboard or quit; always accessible from the taskbar
- **Email Notifications** — Alerts sent directly to your signed-in work mailbox through Agency, without an AI session or LLM tokens
- **Optional Popup Notifications** — Always-on-top windows with clickable links

## Quick Start

### Install dependencies

```bash
pip install -r task_assistant/requirements.txt
```

### Run (with console)

```bash
python -m task_assistant.main
```

### Run (background, no console window)

Double-click `task_assistant/run.pyw` or:

```bash
pythonw task_assistant/run.pyw
```

Then open http://localhost:8347 in your browser (or click the tray icon).

### Notification configuration

The default `email` mode invokes
`$HOME\.copilot\skills\email-send-message\send-email-message.ps1` using
PowerShell 7.1+ (`pwsh` on PATH). Install that helper and its sibling
`common\agency-mcp.ps1`, and sign in to Agency with mailbox access before
running Task Assistant. Set `TASK_ASSISTANT_EMAIL_HELPER` to override the helper path.

Email subjects reflect the alert status: `Timeout` for reminders and PR monitor
timeouts, `CI fails`, `CI passes`, or `PR merged`. The body contains only the
original task URL as plain text, with no description or HTML markup. Outlook
typically displays full URLs as clickable links, depending on client and security
settings. Existing active tasks also use the new default.
Sending runs off the server event loop and does not open popup windows.
Failures and unconfirmed sends appear as **Error** in task history and are logged.
There is no automatic retry or popup fallback; check Sent Items before manually
rerunning a failed task to avoid duplicate mail.

To retain the original popup behavior, set this before launching the app:

```powershell
$env:TASK_ASSISTANT_NOTIFICATION = "popup"
python -m task_assistant.main
```

Unset that variable or set it to `email` to use email. Restart the app after
changing notification configuration.

## Usage

### Add a PR Monitor

1. Click **+ Add Task** in the dashboard
2. Select **PR CI Monitor**
3. Paste a GitHub PR URL (e.g., `https://github.com/Azure/azure-sdk-for-python/pull/1234`)
4. Optionally add a description
5. Click **Create**

The assistant will poll CI status every 5 minutes and send an email when:
- Any CI check fails
- All CI checks pass (except for `azure-rest-api-specs` and `microsoft/typespec` repos)
- The PR is merged

### Add a Reminder

1. Click **+ Add Task** in the dashboard
2. Select **Reminder**
3. Paste a link (Teams message URL, Outlook email URL, etc.)
4. Set the delay in minutes
5. Click **Create**

An email containing the link will be sent when the timer fires.

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tasks` | List all tasks |
| `POST` | `/api/tasks` | Create a new task |
| `DELETE` | `/api/tasks/{id}` | Dismiss/remove a task |
| `GET` | `/api/tasks/{id}/status` | Get task status |

### Create a PR monitor via API

```bash
curl -X POST http://localhost:8347/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"type": "pr_monitor", "link": "https://github.com/Azure/azure-sdk-for-python/pull/1234", "description": "Watch SDK PR"}'
```

### Create a reminder via API

```bash
curl -X POST http://localhost:8347/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"type": "reminder", "link": "https://teams.microsoft.com/l/message/...", "delay_minutes": 30, "description": "Reply to John"}'
```

## Prerequisites

- Python 3.10+
- [GitHub CLI (`gh`)](https://cli.github.com/) — required for PR CI monitoring
- PowerShell 7.1+ and the installed Agency email helper — required for default email notifications
- Windows (system tray and popup notifications use Windows-specific features)

## File Structure

```
task_assistant/
  main.py          # FastAPI app + REST API + startup
  models.py        # Pydantic data models
  storage.py       # JSON file persistence (tasks.json)
  scheduler.py     # Asyncio background task scheduler
  pr_monitor.py    # PR CI polling via gh CLI
  popup.py         # tkinter popup notifications
  email_notification.py # Agency email helper integration (default)
  tray.py          # System tray icon (pystray)
  run.pyw          # Windowless launcher
  static/
    index.html     # Web dashboard
    style.css      # Dashboard styling
    app.js         # Dashboard logic
```
