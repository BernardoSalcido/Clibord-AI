"""Workspace graphical launcher, also used by the optional Windows startup entry."""
from pathlib import Path
import os
import sys

if not getattr(sys, "frozen", False):
    root = Path(__file__).resolve().parents[1]
    # Seafile may share the checkout with Linux; Windows binary wheels are not portable.
    sys.path.insert(0, str(root / "desktop/src"))
    if sys.platform == "win32":
        sys.path.insert(0, str(root / ".deps"))

if __name__ == "__main__":
    try:
        from clipboard_ai.gui import main
        raise SystemExit(main())
    except ImportError as exc:
        message = f"No se pudo cargar la interfaz: {exc}. Instala las dependencias con pip install -e ./desktop[gui]."
        print(message, file=sys.stderr)
        if sys.platform == "win32" and os.environ.get("CLIPBOARD_AI_NO_DIALOG") != "1":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Clipboard AI", 0x10)
        raise SystemExit(1)
