"""Launch Task Assistant without a console window."""
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def launch():
    log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TaskAssistant"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "startup.log").open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            try:
                from task_assistant.main import main

                main(reload=False)
            except Exception:
                traceback.print_exc()
                raise


if __name__ == "__main__":
    launch()
