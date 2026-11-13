"""Workspace launcher; also works with normal pip-installed dependencies."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "desktop/src"))
if sys.platform == "win32":
    sys.path.insert(0, str(root / ".deps"))

from clipboard_ai.cli import main

if __name__ == "__main__":
    main()
