"""Live automatic dock check with a synthetic Qt clipboard, isolated data and no OS writes."""
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
if sys.platform == "win32": sys.path.insert(0, str(root / ".deps"))
sys.path.insert(0, str(root / "desktop/src"))
import argparse
import json
import time
from types import SimpleNamespace
import uuid
from PySide6.QtCore import QObject, QMimeData, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication
from clipboard_ai.ai import AIConfig
from clipboard_ai.gui import DockWindow, STYLE
from clipboard_ai.gui_backend import QtClipboard


class SyntheticClipboard(QObject):
    dataChanged = Signal()
    def __init__(self):
        super().__init__(); self.value = ""; self.picture = None; self.origin = None; self.sequence = 1
    def text(self): return self.value
    def mimeData(self):
        mime = QMimeData()
        if self.picture is not None:
            mime.setImageData(self.picture)
            mime.setUrls([QUrl.fromLocalFile("C:/Pictures/Screenshots/regression.png")])
        else: mime.setText(self.value)
        if self.origin: mime.setData("application/x-clipboard-ai-origin", self.origin)
        return mime
    def image(self): return self.picture
    def setText(self, text):
        # Simulate Ctrl+C publishing a native change without a Qt signal.
        self.value = text; self.picture = None; self.origin = None; self.sequence += 1
    def setMimeData(self, mime):
        self.value = mime.text(); self.picture = None
        self.sequence += 1
        self.origin = mime.data("application/x-clipboard-ai-origin")
        QTimer.singleShot(20, self.dataChanged.emit)
        QTimer.singleShot(180, self.dataChanged.emit)
        def reformat():
            self.origin = None; self.value = self.value.replace("\r\n", "\n").replace("\n", "\r\n")
            self.sequence += 1
            self.dataChanged.emit()
        QTimer.singleShot(300, reformat)
    def setImage(self, image):
        # Simulate Fn+F6: pixels plus a file URL, with only the native sequence changing.
        self.value = ""; self.picture = image; self.origin = None; self.sequence += 1
        QTimer.singleShot(400, self.dataChanged.emit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--image-path", type=Path, help="Captura de prueba en vez de la imagen sintética")
    parser.add_argument("--expect-segments", action="store_true", help="Exigir OCR por partes")
    options = parser.parse_args()
    app = QApplication([]); app.setQuitOnLastWindowClosed(False); app.setStyleSheet(STYLE)
    directory = root / ".test-data" / ("ai-dock-" + uuid.uuid4().hex); directory.mkdir(parents=True)
    AIConfig(image=True, text_mode="spelling", autostart=False).save(directory)
    settings = QSettings(str(directory / "desktop.ini"), QSettings.Format.IniFormat)
    settings.setValue("keys/show", ""); settings.setValue("keys/send", ""); settings.setValue("notifications", False)
    clipboard = SyntheticClipboard(); bridge = QtClipboard(clipboard, sequence=lambda: clipboard.sequence)
    window = DockWindow(SimpleNamespace(data_dir=directory, bind="127.0.0.1", port=0, advertise=None), settings, clipboard=bridge)
    reports = []; events = []; statuses = []; errors = []; failures = []
    bridge.external_changed.connect(events.append)
    window.backend.completed.connect(lambda action, value: reports.append(value) if action == "ai_result" else None)
    window.backend.error.connect(errors.append); window.backend.ai_state.connect(statuses.append)
    stage = 0; ready_at = None; started = time.monotonic()
    def tick():
        global stage, ready_at
        try:
            assert not errors, errors
            assert time.monotonic() - started < 90, statuses
            if stage == 0 and statuses and statuses[-1] == "IA lista":
                if options.image_path:
                    image = QImage(str(options.image_path))
                    assert not image.isNull(), "No se pudo leer la captura de prueba"
                else:
                    image = QImage(640, 150, QImage.Format.Format_RGB32); image.fill(QColor("white"))
                    painter = QPainter(image); painter.setPen(QColor("black")); painter.setFont(QFont("Arial", 28))
                    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "Clipboard AI\nOCR 12345"); painter.end()
                clipboard.setImage(image); stage = 1
            elif stage == 1 and len(reports) == 1:
                assert reports[0]["written"], reports[0]
                assert (len(clipboard.text()) > 100 if options.image_path else "OCR 12345" in clipboard.text()), clipboard.text()
                if options.expect_segments:
                    assert reports[0]["stats"].get("segments", 0) >= 2, reports[0]
                print("Automatic image to clipboard: passed", flush=True)
                clipboard.setText("Este texxto tiene un eror ortografico."); stage = 2
            elif stage == 2 and len(reports) == 2:
                assert reports[1]["written"] and clipboard.text() == "Este texto tiene un error ortográfico.", clipboard.text()
                assert len(events) == 2, "An own write triggered another AI input"
                ready_at = time.monotonic(); stage = 3
            elif stage == 3 and time.monotonic() - ready_at > .8:
                assert len(reports) == 2 and len(events) == 2, "AI loop detected"
                window.show(); window.toggle_actions(); app.processEvents()
                window.grab().save(str(directory / "dock.png"))
                print("Automatic spelling and no echo loop: passed", flush=True)
                timer.stop(); window.quit_app()
        except BaseException as exc:
            failures.append(repr(exc)); timer.stop(); window.quit_app()
    timer = QTimer(); timer.timeout.connect(tick); timer.start(50)
    window.backend.start(); app.exec()
    window.backend.thread.join(5)
    report = dict(passed=not failures, failures=failures, results=reports, input_events=len(events), states=statuses)
    (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report:", directory / "result.json", flush=True)
    if failures: raise SystemExit(str(failures))
