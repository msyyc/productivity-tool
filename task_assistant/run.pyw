"""Launch Task Assistant without a console window."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from task_assistant.main import main
main()
