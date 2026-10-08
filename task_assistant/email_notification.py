import json
import os
import subprocess
from pathlib import Path


EMAIL_SUBJECTS = {
    "PR Merged": "PR merged",
    "CI Failed": "CI fails",
    "CI Passed": "CI passes",
    "\u23f0 PR Monitor Timeout": "Timeout",
    "\u23f0 Reminder": "Timeout",
}


def send_email(title: str, message: str, link: str) -> None:
    """Send a status subject and plain-text URL body, without retrying."""
    helper = Path(
        os.environ.get(
            "TASK_ASSISTANT_EMAIL_HELPER",
            str(Path.home() / ".copilot" / "skills" / "email-send-message" / "send-email-message.ps1"),
        )
    )
    if not helper.is_file():
        raise FileNotFoundError(f"Email helper not found: {helper}")
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(helper),
            "-Subject",
            EMAIL_SUBJECTS.get(title, title),
            "-Body",
            link,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Email helper exited with code {result.returncode}")
    confirmation = json.loads(result.stdout)
    if not isinstance(confirmation, dict) or confirmation.get("status") != "sent" or not confirmation.get("messageId"):
        raise RuntimeError("Email helper did not confirm delivery with a message ID")
