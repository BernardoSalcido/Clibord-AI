"""Explicit live smoke test using synthetic inputs; never reads/writes the OS clipboard."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

root = Path(__file__).resolve().parents[1]
if sys.platform == "win32": sys.path.insert(0, str(root / ".deps"))
sys.path.insert(0, str(root / "desktop/src"))

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication
from clipboard_ai.ai import AIConfig, LocalAI
from clipboard_ai.gui import warmup_image


async def check(config, warm, image, directory):
    states = []
    def status(value):
        states.append(value); print(value, flush=True)
    client = LocalAI(config, status)
    report = dict(endpoint=config.endpoint, model=config.model)
    try:
        await client.prepare(warm)
        for action, text, picture in (
            ("spelling", "Este texxto tiene un eror ortografico.", None),
            ("grammar", "She go to the lab every day.", None),
            ("image", "", image),
        ):
            result, stats = await client.process(action, text, picture)
            report[action] = dict(input=text, output=result, stats=stats)
            print(action, json.dumps(report[action], ensure_ascii=False), flush=True)
        assert "error" in report["spelling"]["output"] and "texto" in report["spelling"]["output"]
        assert "goes" in report["grammar"]["output"]
        assert report["grammar"]["stats"]["reasoning_output_tokens"] > 0
        assert "OCR 12345" in report["image"]["output"]
        report["passed"] = True
    finally:
        report["states"] = states
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await client.close()
    print("Report:", directory / "result.json", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    app = QApplication([])
    image = QImage(640, 150, QImage.Format.Format_RGB32); image.fill(QColor("white"))
    painter = QPainter(image); painter.setPen(QColor("black")); painter.setFont(QFont("Arial", 28))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "Clipboard AI\nOCR 12345"); painter.end()
    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly); image.save(buffer, "PNG")
    directory = root / ".test-data" / ("ai-live-" + uuid.uuid4().hex); directory.mkdir(parents=True)
    image.save(str(directory / "input.png"))
    asyncio.run(check(AIConfig(autostart=False), warmup_image(), bytes(data), directory))
