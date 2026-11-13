"""OS-owned lock shared by terminal and graphical launchers; crashes release it."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, directory):
        self.path = Path(directory) / "desktop.lock"
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    stream.write(b"0"); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None

    def __enter__(self):
        if not self.acquire():
            raise OSError("Clipboard AI ya está abierto con esta carpeta de datos. Abre el dock desde la bandeja o cierra la terminal anterior.")
        return self

    def __exit__(self, *args):
        self.close()
